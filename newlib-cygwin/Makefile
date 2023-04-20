# Makefile for newlib/Cygwin

# This file is part of SimpleTuner

# Copyright (C) 2021-2023 Embecosm <www.embecosm.com>
# Contributor Maxim Blinov <maxim.blinov@embecosm.com>

# SPDX-License-Identifier: GPL-3.0-or-later

.PHONY: all clean

WORKER_CONTEXT_NAME := newlib-cygwin.tar.gz

all: $(WORKER_CONTEXT_NAME)

newlib-cygwin/:
	git clone git://sourceware.org/git/newlib-cygwin.git

$(WORKER_CONTEXT_NAME): newlib-cygwin/
	tar -czf $@ -C $^ .

clean:
	rm -rf $(WORKER_CONTEXT_NAME) newlib-cygwin/
