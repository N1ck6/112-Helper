#!/bin/sh
# Health check для Docker.

asterisk -rx "core show version" > /dev/null 2>&1
exit $?
