#!/usr/bin/env python3
"""Generic filesystem job queue + global GPU serialization engine.

This module is copied verbatim into each GPU service's cli/ directory by
bootstrap service add --support=python. It provides a single-consumer
filesystem queue and a global flock so only one model is ever resident in VRAM
across every service sharing the same GPU_LOCK_PATH.

Queue layout (all inside QUEUE_DIR, same filesystem so rename is atomic):

    QUEUE_DIR/tmp         partially written descriptors (never claimed)
    QUEUE_DIR/pending     ready to process
    QUEUE_DIR/processing  claimed by the running consumer
    QUEUE_DIR/done        completed
    QUEUE_DIR/failed      permanently failed or corrupt

Descriptors are JSON objects whose fields are defined by the producing service;
the queue only relies on the <name>.json filename.

A consumer polls its own queue. When a job appears it claims one, acquires the
global flock at GPU_LOCK_PATH, loads its model, processes the claimed job and
drains any further claimable jobs, unloads the model to free VRAM, releases the
flock, then moves each job to done/ or failed/. Because there is one consumer
per queue, anything left in processing/ at startup is from a crashed run and is
swept back to pending/.
"""

import fcntl
import json
import os
import signal
import sys
import tempfile
import time
import urllib.request

QUEUE_SUBDIRS = ("tmp", "pending", "processing", "done", "failed")


def ensure_dirs(queue_dir):
    for name in QUEUE_SUBDIRS:
        os.makedirs(os.path.join(queue_dir, name), exist_ok=True)


def sweep_stale(queue_dir):
    # A single consumer owns each queue, so any descriptor still in processing/
    # at startup belongs to a crashed run and is safe to requeue.
    processing = os.path.join(queue_dir, "processing")
    pending = os.path.join(queue_dir, "pending")
    if not os.path.isdir(processing):
        return
    for name in os.listdir(processing):
        if not name.endswith(".json"):
            continue
        try:
            os.rename(os.path.join(processing, name), os.path.join(pending, name))
        except OSError as error:
            sys.stderr.write("sweep_stale could not requeue " + name + ": " + str(error) + "\n")


def _pending_names_oldest_first(pending):
    try:
        entries = []
        for name in os.listdir(pending):
            if not name.endswith(".json"):
                continue
            path = os.path.join(pending, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            entries.append((mtime, name))
        entries.sort()
        return [name for _, name in entries]
    except FileNotFoundError:
        return []


def claim(queue_dir):
    # Atomically move the oldest pending descriptor into processing/. rename is
    # atomic on a single filesystem, so a lost race just moves to the next name.
    pending = os.path.join(queue_dir, "pending")
    processing = os.path.join(queue_dir, "processing")
    for name in _pending_names_oldest_first(pending):
        src = os.path.join(pending, name)
        dst = os.path.join(processing, name)
        try:
            os.rename(src, dst)
        except OSError:
            continue
        try:
            with open(dst, "r") as handle:
                descriptor = json.load(handle)
        except (OSError, ValueError) as error:
            sys.stderr.write("claim found corrupt descriptor " + name + ": " + str(error) + "\n")
            _move(dst, os.path.join(queue_dir, "failed", name))
            continue
        descriptor["_name"] = name
        descriptor["_path"] = dst
        return descriptor
    return None


def _move(src, dst):
    try:
        os.rename(src, dst)
    except OSError as error:
        sys.stderr.write("could not move " + src + " to " + dst + ": " + str(error) + "\n")


def _finish(queue_dir, descriptor, ok):
    name = descriptor.get("_name")
    src = descriptor.get("_path")
    if not name or not src:
        return
    target = "done" if ok else "failed"
    _move(src, os.path.join(queue_dir, target, name))


def acquire_lock(lock_path):
    # Blocking exclusive flock on the shared GPU lock. The returned handle must
    # stay referenced for the duration of GPU work; closing it releases.
    lock_dir = os.path.dirname(lock_path)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    handle = open(lock_path, "w")
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def release_lock(handle):
    if handle is None:
        return
    try:
        fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        handle.close()


def fetch_to_temp(url):
    # Dev fetch: plain HTTP GET to a temp file (dedup + hashing already done by
    # the Node ingest path, so no hashing is needed here). Prod S3 presign
    # parity is a documented follow-up.
    request = urllib.request.Request(url, headers={"User-Agent": "fsqueue"})
    with urllib.request.urlopen(request) as response:
        status = getattr(response, "status", 200)
        if status != 200:
            raise ValueError("Failed to fetch url, status " + str(status))
        data = response.read()
    if not data:
        raise ValueError("Fetched empty body")
    fd, path = tempfile.mkstemp(prefix="fsq-")
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return path


def remove_temp(path):
    if not path:
        return
    try:
        os.remove(path)
    except OSError:
        pass


def _drain(queue_dir, lock_path, handler, first):
    # Hold the global GPU lock for a whole batch: load once, process every
    # claimable job, then unload to free VRAM before releasing the lock.
    lock_handle = acquire_lock(lock_path)
    try:
        try:
            handler.load()
        except Exception as error:
            sys.stderr.write("model load failed: " + str(error) + "\n")
            _finish(queue_dir, first, ok=False)
            return
        try:
            descriptor = first
            while descriptor is not None:
                try:
                    handler.process(descriptor)
                    _finish(queue_dir, descriptor, ok=True)
                except Exception as error:
                    sys.stderr.write("job " + str(descriptor.get("_name")) + " failed: " + str(error) + "\n")
                    _finish(queue_dir, descriptor, ok=False)
                descriptor = claim(queue_dir)
        finally:
            try:
                handler.unload()
            except Exception as error:
                sys.stderr.write("model unload failed: " + str(error) + "\n")
    finally:
        release_lock(lock_handle)


def run_consumer(queue_dir, lock_path, handler, poll_ms=1000):
    ensure_dirs(queue_dir)
    sweep_stale(queue_dir)

    state = {"running": True}

    def handle_signal(signum, frame):
        state["running"] = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    poll_seconds = max(poll_ms, 1) / 1000.0
    sys.stderr.write("consumer ready, watching " + queue_dir + "\n")
    sys.stderr.flush()

    while state["running"]:
        descriptor = claim(queue_dir)
        if descriptor is None:
            time.sleep(poll_seconds)
            continue
        _drain(queue_dir, lock_path, handler, descriptor)
