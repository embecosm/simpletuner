.PHONY: all clean

WORKER_CONTEXT_NAME := newlib-cygwin.tar.gz

all: $(WORKER_CONTEXT_NAME)

newlib-cygwin/:
	git clone git://sourceware.org/git/newlib-cygwin.git

$(WORKER_CONTEXT_NAME): newlib-cygwin/
	tar -czf $@ -C $^ .

clean:
	rm -rf $(WORKER_CONTEXT_NAME) newlib-cygwin/
