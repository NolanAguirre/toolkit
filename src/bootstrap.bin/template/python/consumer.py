#!/usr/bin/env python3
"""Filesystem queue consumer.

Drains QUEUE_DIR one job at a time while holding the GPU flock at
GPU_LOCK_PATH. Fill in load, process and unload with the service's model work.
"""

import os
import sys

import fsqueue


class Handler:
    def load(self):
        # Load the model into memory. Called once per batch with the lock held.
        pass

    def process(self, descriptor):
        # Handle one claimed job. Raise to move it to failed/.
        pass

    def unload(self):
        # Free the model and any GPU memory before the lock is released.
        pass


def main():
    queue_dir = os.environ.get("QUEUE_DIR")
    lock_path = os.environ.get("GPU_LOCK_PATH")
    if not queue_dir:
        sys.exit("QUEUE_DIR is not set")
    if not lock_path:
        sys.exit("GPU_LOCK_PATH is not set")
    fsqueue.run_consumer(queue_dir, lock_path, Handler())


if __name__ == "__main__":
    main()
