.PHONY: all clean

WORKER_CONTEXT_NAME := eh1.tar.gz

all: $(WORKER_CONTEXT_NAME)

Cores-SweRV/:
	git clone https://github.com/chipsalliance/Cores-SweRV \
	&& cd Cores-SweRV \
	&& git checkout v1.9 \
	&& git apply ../0001-Fix-makefile.patch \
	&& git apply ../0002-move-eh-frame-to-extdata.patch

Cores-SweRV/obj_dir/Vtb_top: Cores-SweRV/
	cd Cores-SweRV/ \
	&& RV_ROOT=$(CURDIR)/Cores-SweRV \
		configs/swerv.config -target=high_perf \
	&& RV_ROOT=$(CURDIR)/Cores-SweRV \
		$(MAKE) -f tools/Makefile verilator-build

$(WORKER_CONTEXT_NAME): Cores-SweRV/obj_dir/Vtb_top
	tar -czf $@ -C Cores-SweRV/ .

clean:
	rm -rf $(WORKER_CONTEXT_NAME) Cores-SweRV/
