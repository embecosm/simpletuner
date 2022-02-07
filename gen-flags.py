#!/usr/bin/env python3
import json
import logging;
import argparse;

from flag import Flag;
from gcc import GCCDriver;

parser = argparse.ArgumentParser(description='Generate configuration file for use by simpletuner.');

parser.add_argument("--cc", default=None,
                    help="C compiler to use for initial flag validation.");

parser.add_argument("--base-cflags", default=None,
                    metavar='-flag', type=str, nargs='+',
                    help="C flags to start with. These can help speed up combined elimination. If you're trying to minimize size, try '-Os'. If you're trying to maximise performance, try '-O3' or '-Ofast'.");

args = parser.parse_args();

def discretise_params(params):
    logger = logging.getLogger("gen-flags.py");
    flags = [];

    for k, v in params.items():
        flattened = [];

        if v["min"] is None:
            # print("Skipping {} as it is unbounded".format(k), file=sys.stderr);
            # continue;
            flattened.append("--param={}={}".format(k, v["default"]));

            for i in range(0, 21):
                flattened.append("--param={}={}".format(k, i));

            for i in range(30, 101, 10):
                flattened.append("--param={}={}".format(k, i));

        else:
            logger.info("Expanding {}: (default: --param={}={})" \
                        .format(k, k, v["default"]));

        # Treat the unbounded parameters specially
        unbounded_p = v["min"] == 0 and v["max"] == 2147483647;

        n_options = v["max"] - v["min"] + 1;

        if unbounded_p:
            if v["default"] == 0:
                flattened.append("--param={}={}".format(k, v["default"]));

                for i in range(0, 101, 5):
                    if i == v["default"]:
                        continue;

                    flattened.append("--param={}={}".format(k, i));

            else:
                half_range = v["default"];
                flattened.append("--param={}={}".format(k, half_range));

                full_range = half_range * 2;
                for i in range(0, full_range + 1,
                               full_range // 10 if full_range >= 10 else 1):
                    if i == v["default"]:
                        continue;

                    flattened.append("--param={}={}".format(k, i));

            flags.append(Flag(k, flattened));
            continue;

        if n_options <= 25:
            flattened.append("--param={}={}".format(k, v["default"]));

            for i in range(v["min"], v["max"] + 1):
                if i == v["default"]:
                    continue;

                flattened.append("--param={}={}".format(k, i));
        else:
            # `... v["max"]` is correct - do the `v["max"] + 1` case
            # explicitly, so we can guarantee to always test it
            flattened.append("--param={}={}".format(k, v["default"]));

            for i in range(v["min"], v["max"], n_options // 10):
                if i == v["default"]:
                    continue;

                flattened.append("--param={}={}".format(k, i));

            # Make sure we always test the maximum value
            flattened.append("--param={}={}".format(k, v["max"]));

            flags.append(Flag(k, flattened));

    return flags;

def get_global_flags():
    flags = [];

    flags.append(Flag("-O", ["-O0", "-O1", "-O2", "-O3", "-Ofast", "-Og", "-Os"]));

    return flags;

def get_target_flags():
    logger = logging.getLogger("SimpleTuner-Driver")
    flags = [];

    flags.append(Flag("-mbranch-cost", ["-mbranch-cost={}".format(i) for i in range(20)]));
    flags.append(Flag("-mcmodel", ["-mcmodel=medlow", "-mcmodel=medany"]));
    flags.append(Flag("-mrelax", ["-mrelax", "-mno-relax"]));
    flags.append(Flag("-msave-restore", ["-msave-restore", "-mno-save-restore"]));
    flags.append(Flag("-mshorten-memrefs", ["-mshorten-memrefs", "-mno-shorten-memrefs"]));
    flags.append(Flag("-msmall-data-limit", ["-msmall-data-limit={}".format(i) for i in range(20)]));
    flags.append(Flag("-mstrict-align", ["-mstrict-align", "-mno-strict-align"]));

    flags.append(Flag("-mtune",
         ["-mtune=size",
          "-mtune=rocket",
          "-mtune=sifive-3-series",
          "-mtune=sifive-5-series",
          "-mtune=sifive-7-series"]));

    return flags;

def main():
    logging.basicConfig(format="[%(levelname)s] %(name)s: %(message)s");
    logger = logging.getLogger("gen-flags.py");

    logging.root.setLevel(logging.NOTSET);

    if args.cc is not None:
        logger.info("Will be using the C compiler at \"{}\" to check flags.".format(args.cc));
    else:
        logger.error("You must provide a path to a C compiler. Aborting.");
        exit(1);

    driver = GCCDriver(args.cc);
    logger.info("GCC Version: {}".format(driver.get_version()));
    logger.info("GCC Target: {}".format(driver.get_target()));

    if args.base_cflags is not None:
        logger.info("Will be using the following base C flags: \"{}\"".format(args.base_cflags));
        cflags = [e.strip() for e in args.base_cflags.split()]
    else:
        logger.warning("No base C flags provided: This may pessimize combined elimination results. Continuing anyway...");
        cflags = [];

    flags = [];

    global_flags = get_global_flags();
    flags += global_flags;

    params = driver.get_params(cflags);
    flags += discretise_params(params);

    optimizations = driver.get_optimizations(cflags);
    flags += optimizations;

    target_flags = get_target_flags();
    flags += target_flags;

    # print(flags);
    print(json.dumps(flags, indent=4, cls=Flag.FlagEncoder));

if __name__ == "__main__":
    main();
