#!/usr/bin/env python3
import os, sys, re, subprocess, logging;
from flag import Flag;

class GCCDriver:
    class Version:
        def __init__(self, major, minor, patch):
            self.major = major;
            self.minor = minor;
            self.patch = patch;

        def __repr__(self):
            return "{}.{}.{}".format(self.major, self.minor, self.patch);

        def __str__(self):
            return repr(self);

    def __init__(self, cc_path):
        # self.bindir = bindir;
        # self.cc = os.path.join(self.bindir, tool_prefix + "gcc");
        self.cc = cc_path;
        # self.logger = logging.getLogger("GCCDriver");
        # self.logger.info("Using gcc = \"{}\"".format(self.cc));

    def get_version(self):
        res = subprocess.Popen([self.cc, "-v"],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            return None;

        lines = [line.strip() for line in stderr.decode("utf-8").split('\n') if len(line.strip()) > 0];

        version_re = re.compile(r"gcc version ([0-9]+)\.([0-9]+)\.([0-9]+)");
        version = None;

        for line in lines:
            mo = version_re.search(line);
            if not mo:
                continue;

            version = GCCDriver.Version(
                int(mo.group(1)),
                int(mo.group(2)),
                int(mo.group(3))
            );

            break;

        return version;

    def get_target(self):
        res = subprocess.Popen([self.cc, "-v"],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            return None;

        lines = [line.strip() for line in stderr.decode("utf-8").split('\n') if len(line.strip()) > 0];

        target_re = re.compile(r"Target: (\S+)");
        target = None;

        for line in lines:
            mo = target_re.search(line);
            if not mo:
                continue;

            target = mo.group(1);
            break;

        return target;

    def get_params(self, cflags=None):
        params = {};

        version = self.get_version();
        if version is None:
            # self.logger.error("Failed to fetch GCC version");
            sys.exit(1);

        target = self.get_target();
        if target is None:
            # self.logger.error("Failed to fetch GCC version");
            sys.exit(1);

        # self.logger.info("GCC Appears to be version {}, targeting {}" \
        #                  .format(str(version), target));

        if version.major > 9:
            re_param_bounded = re.compile(
                r"\-\-param\=([a-zA-Z0-9\-]+)\=<(\-?[0-9]+),(\-?[0-9]+)>\s+(\-?[0-9]+)");

            re_param_unbounded = re.compile(
                r"\-\-param\=([a-zA-Z0-9\-]+)\=\s+(\-?[0-9]+)");
        else:
            re_param_bounded = re.compile(
                r"([a-zA-Z0-9\-]+)\s+default (\-?[0-9]+) minimum (\-?[0-9]+) maximum (\-?[0-9]+)");

        if cflags is not None:
            cmd = [self.cc] + cflags + ["-Q", "--help=params"]
        else:
            cmd = [self.cc, "-Q", "--help=params"]

        res = subprocess.Popen(cmd,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            # self.logger.info("gcc exited with {}".format(res.returncode));
            sys.exit(1);

        stdout = stdout.decode("utf-8").strip();
        lines = stdout.split('\n');

        # The first line is always
        # ```
        #  The following options control parameters:
        #  ...
        # ```
        # So remove it.
        lines = lines[1:];

        for lineno, line in enumerate(lines):
            # Try matching a fully-constrained parameter, e.g.
            #   --param=uninit-control-dep-attempts=<1,65536>       1000
            mo = re_param_bounded.search(line);
            if mo:
                # print("Found groups: {}".format(",".join([mo.group(i) for i in range(len(mo.groups()))])));
                # print("Found groups: {}".format(",".join([str(i) for i in range(10)])));

                param_name = mo.group(1);
                if version.major > 9:
                    param_range = (int(mo.group(2)), int(mo.group(3)));
                    param_default = int(mo.group(4));
                else:
                    param_range = (int(mo.group(3)), int(mo.group(4)));
                    param_default = int(mo.group(2));

                # print("line {}: Parsed parameter \"{}\", range [{},{}], default {}"\
                #       .format(lineno, param_name, param_range[0], param_range[1],
                #               param_default));
                params[param_name] = {"min": param_range[0],
                                      "max": param_range[1],
                                      "default": param_default};
                continue;

            # Try matching an unconstrained parameter, e.g.
            #   --param=sra-max-propagations=         32
            # Note: these only exist in GCC 10 and above
            if version.major < 10:
                continue;

            mo = re_param_unbounded.search(line);
            if mo:
                param_name = mo.group(1);
                param_range = None;
                param_default = int(mo.group(2));

                # print("line {}: Parsed parameter \"{}\", unconstrained, default {}"\
                #       .format(lineno, param_name, param_default));
                params[param_name] = {"min": 0,
                                      "max": 2147483647,
                                      "default": param_default};
                continue;

            # If we're still here, it may be because we got a strange
            # --param flag, e.g.
            #
            #   --param=parloops-schedule=[static|dynamic|guided|auto|runtime]        static
            # or
            #   --param=lazy-modules=                 [available in C++]
            # self.logger.warning("line {}: Unrecognized parameter \"{}\"" \
            #       .format(lineno, line));

        # Hack: The following params are bugged:
        # --param=logical-op-non-short-circuit
        # --param=vect-max-peeling-for-alignment

        # Because in the gcc/params.opt file it is specified as a
        # IntegerRange(-1, 1), but the command line parser treats it like
        # a UInteger. Hence, even though the default is -1, we can't
        # actually specify -1 at the command line without getting an
        # error. So lets omit it for now.

        if "logical-op-non-short-circuit" in params:
            params["logical-op-non-short-circuit"]["min"] = 0;

        if "vect-max-peeling-for-alignment" in params:
            params["vect-max-peeling-for-alignment"]["min"] = 0;

        # Causes GCC to crash if we set this to too high a value. Probably
        # not relevant to optimisation anyway.
        if "min-nondebug-insn-uid" in params:
            del params["min-nondebug-insn-uid"];

        # Remove flags which are hopefully irrelevant to speed
        # optimisation
        to_removes = [
            "asan-globals",
            "asan-instrument-allocas",
            "asan-instrument-reads",
            "asan-instrument-writes",
            "asan-instrumentation-with-call-threshold",
            "asan-memintrin",
            "asan-stack",
            "asan-use-after-return",
            "hwasan-instrument-stack",
            "hwasan-random-frame-tag",
            "hwasan-instrument-allocas",
            "hwasan-instrument-reads",
            "hwasan-instrument-writes",
            "hwasan-instrument-mem-intrinsics",

            "cxx-max-namespaces-for-diagnostic-help",

            "ggc-min-expand",
            "ggc-min-heapsize",

            "graphite-allow-codegen-errors",
            "hash-table-verification-limit",

            "lazy-modules",

            "lto-max-partition",
            "lto-max-streaming-parallelism",
            "lto-min-partition",
            "lto-partitions",

            # OMP is probably not relevant
            "parloops-chunk-size",
            "parloops-min-per-thread",

            "profile-func-internal-id",
            "tm-max-aggregate-size",
            "tracer-dynamic-coverage",
            "tracer-dynamic-coverage-feedback",
            "tracer-max-code-growth",
            "tracer-min-branch-probability",
            "tracer-min-branch-probability-feedback",
            "tracer-min-branch-ratio",

            "tsan-distinguish-volatile",
            "tsan-instrument-func-entry-exit",

            "use-canonical-types",

            # GCC likes to advertise parameters that can allegedly assume the value
            # of -1, but in practise cannot. Remove them too.
            "prefetch-minimum-stride",
            "sched-autopref-queue-depth",
            "vect-max-peeling-for-alignment",
        ];

        for to_remove in to_removes:
            if to_remove in params:
                del params[to_remove];

        return params;

    def get_optimizations(self, cflags):
        flags = [];

        re_param_simple = re.compile(r"\-f([a-zA-Z0-9\-]+)\s+(\[disabled\]|\[enabled\])?");

        if cflags is not None:
            cmd = [self.cc] + cflags + ["-Q", "--help=optimizers"]
        else:
            cmd = [self.cc, "-Q", "--help=optimizers"]

        res = subprocess.Popen(cmd,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            # self.logger.error("[ERROR] gcc exited with {}".format(res.returncode));
            sys.exit(1);

        stdout = stdout.decode("utf-8").strip();
        lines = stdout.split('\n');

        # The first line is always
        # ```
        #  The following options control parameters:
        #  ...
        # ```
        # So remove it.
        lines = lines[1:];

        for lineno, line in enumerate(lines):
            # Try matching a simple flag, e.g.
            #     -ftree-partial-pre                    [disabled]
            mo = re_param_simple.search(line);
            if mo:
                # self.logger.debug("Found groups: {}".format(",".join([mo.group(i) for i in range(len(mo.groups()))])));
                # print("Found groups: {}".format(",".join([str(i) for i in range(10)])));
                flag_name = mo.group(1);

                # Remove flags which are hopefully irrelevant to speed
                # optimisation, or otherwise problematic
                to_skip = [
                    "live-patching",
                    "ipa-profile",
                    "profile-use",
                    "profile-generate",
                    "branch-probabilities",
                    "auto-profile",
                    "fexceptions",

                    # This generates annoying '-.opt-record.json.gz' in
                    # the working directory of the python script, which
                    # then has to be deleted via $ rm --
                    # '-.opt-record.json.gz'.
                    "fsave-optimization-record",

                    "stack-protector",
                    "stack-protector-all",
                    "stack-protector-strong",
                    "stack-protector-explicit",
                ];

                if flag_name in to_skip:
                    continue;

                # print("line {}: Parsed parameter \"{}\", range [{},{}], default {}"\
                #       .format(lineno, param_name, param_range[0], param_range[1],
                #               param_default));

                if mo.group(2) is not None:
                    if mo.group(2) == "[enabled]":
                        flags.append(Flag("-f" + flag_name,
                                          ["-f" + flag_name,
                                           "-fno-" + flag_name]));
                    else:
                        flags.append(Flag("-f" + flag_name,
                                          ["-fno-" + flag_name,
                                           "-f" + flag_name]));

                # flags.append("-f" + flag_name);
                # flags.append("-fno-" + flag_name);

                continue;

            # If we're still here, it may be because we got a strange
            # flag, e.g.
            #
            #   -fvect-cost-model=[unlimited|dynamic|cheap|very-cheap]        [default]
            # or
            #     -flifetime-dse=<0,2>                  2
            # self.logger.warning("line {}: Unrecognized parameter \"{}\"".format(lineno, line));

        # print("Got stdout:\n", "\n".join(lines));
        return flags;

    def check_flag(self, flag):
        # self.logger.info("check_gcc_flag(): Checking {} variant of {} ({}/{})" \
        #                  .format(flag.flags[state], flag.name, state, flag.n_states - 1));

        cmd = [self.cc,
               "-fno-diagnostics-color",  # Don't leave control codes in stdout/stderr
               "-S",  # Don't worry about the assembler or linker
               "-o", "/dev/null",  # No output
               flag,
               "-x", "c",  # Must specify language if taking input from stdin
               "-"  # Take input from stdin
               ];

        res = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        return res.returncode == 0;

def main():
    # Logging initialization code taken from here:
    # https://stackoverflow.com/a/56144390
    # Logging format handling and file/stream handling from here:
    # https://stackoverflow.com/a/46098711
    logging.basicConfig(
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            # We don't create the file log output yet, because we haven't created the workspace
            # directory yet.
            # logging.FileHandler("log.txt"),
            logging.StreamHandler()
        ]
    );

    # Set the priority to NOTSET (i.e. report everything.)
    logging.root.setLevel(logging.NOTSET);

    gcc = GCCDriver("/home/maxim/Downloads/riscv32-embecosm-ubuntu1804-gcc11.2.0/bin", "riscv32-unknown-elf-");
    print("GCC Version: {}".format(gcc.get_version()));
    print("GCC Target: {}".format(gcc.get_target()));

    # params = gcc.get_params(None if len(sys.argv[1:]) == 0 else sys.argv[1:]);
    # for k, v in params.items():
    #     print(k, v);

    optimizations = gcc.get_optimizations(None if len(sys.argv[1:]) == 0 else sys.argv[1:]);
    for opt in optimizations:
        print(opt);

if __name__ == "__main__":
    main();
