#!/bin/sh

# Replace __KEY__ with TEMPLATE_KEY literally, including multiline fragments.
# Only scan the source: inserted values are never evaluated or expanded again.
template_render() {
    awk '
        {
            line = $0
            rendered = ""
            while (match(line, /__[A-Z][A-Z0-9_]*__/)) {
                key = "TEMPLATE_" substr(line, RSTART + 2, RLENGTH - 4)
                if (!(key in ENVIRON)) {
                    print "error: missing template value: " key > "/dev/stderr"
                    exit 1
                }
                rendered = rendered substr(line, 1, RSTART - 1) ENVIRON[key]
                line = substr(line, RSTART + RLENGTH)
            }
            print rendered line
        }
    ' "$1"
}
