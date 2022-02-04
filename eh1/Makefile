.PHONY: all clean

WORKER_CONTEXT_NAME := eh1.tar.gz

all: $(WORKER_CONTEXT_NAME)

Cores-SweRV/:
	git clone https://github.com/chipsalliance/Cores-SweRV \
	&& cd Cores-SweRV \
	&& git checkout v1.9 \
	&& git apply ../0001-Fix-makefile.patch \
	&& git apply ../0002-move-eh-frame-to-extdata.patch

Cores-SweRV/obj_dir/Vtb_top: Cores-SweRV/ install/bin/verilator
	cd Cores-SweRV/ \
	&& PATH=$(abspath install/bin):$(PATH) \
		RV_ROOT=$(CURDIR)/Cores-SweRV \
		configs/swerv.config -target=high_perf \
	&& PATH=$(abspath install/bin):$(PATH) \
		RV_ROOT=$(CURDIR)/Cores-SweRV \
		$(MAKE) -f tools/Makefile verilator-build

$(WORKER_CONTEXT_NAME): Cores-SweRV/obj_dir/Vtb_top
	tar -czf $@ -C Cores-SweRV/ .

verilator/:
	git clone https://github.com/verilator/verilator.git \
	&& git -C verilator checkout v4.218

install/bin/verilator: verilator/
	cd verilator/ \
	&& autoconf \
	&& ./configure --prefix=$(abspath install) \
	&& make -j $(shell nproc) \
	&& make -j $(shell nproc) install

clean:
	rm -rf $(WORKER_CONTEXT_NAME) Cores-SweRV/
