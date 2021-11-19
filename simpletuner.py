#!/usr/bin/env python3
import os, sys, re, time, random, subprocess, shutil, string;
from datetime import datetime;
import copy;

import multiprocessing as mp;
import argparse;

# See: https://stackoverflow.com/a/13941865 - we need this to catch
# `queue.Empty` exceptions
import queue; # Called "Queue" in Python 2

parser = argparse.ArgumentParser(description='Explore compiler flag performance in parallel');

def greater_than_one(value):
    ivalue = int(value)
    if ivalue < 1:
        raise argparse.ArgumentTypeError(
            "{} must be an integer greater than 1".format(value));
    return ivalue

parser.add_argument("-j", "--processes", type=greater_than_one,
                    default=None, # Will use mp.cpu_count();
                    help="Number of processes to spawn");

parser.add_argument("--context", default=None,
                    help="Specify which \"backend\" to use. This is a user-defined classname.");

parser.add_argument("--flag-baselines-file", default=None,
                    help="Specify file that contains a comma-separated"
                    "file containing lines of <score,flag> tuples.");

parser.add_argument("--cc", default="cc",
                    help="PLEASE make sure that this compiler"
                    " is the same that you WorkerContext will be using!");

parser.add_argument("--target-flags-file", default=None,
                    help="Additional flags file that will be appended"
                    " to generic flags  provided by the compiler."
                    " Typically you would put target-specific stuff here"
                    ", e.g. -mtune, -mcpu, etc.");

parser.add_argument("--setup-workspace-only", action="store_true",
                    help="Exit after setting up a workspace for each"
                    " worker thread. Useful for when debugging the"
                    " WorkerContext.init_workspace procedure.");

args = parser.parse_args();

# CC = "riscv32-unknown-elf-gcc";
# CC = r'C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Tools\MSVC\14.28.29910\bin\Hostx64\x64\cl.exe';

workspace_file_all = None;
workspace_file_stdout = None;
workspace_file_stderr = None;

def debug(*args, **kwargs):
    global workspace_file_all;
    global workspace_file_stdout;
    global workspace_file_stderr;

    now = datetime.now().strftime("%d-%b-%Y %H:%M:%S");

    print("[debug] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=sys.stderr);
    if workspace_file_all:
        print("[debug] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=workspace_file_all);
        workspace_file_all.flush();

    if workspace_file_stderr:
        print("[debug] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=workspace_file_stderr);
        workspace_file_stderr.flush();

def info(*args, **kwargs):
    global workspace_file_all;
    global workspace_file_stdout;
    global workspace_file_stderr;

    now = datetime.now().strftime("%d-%b-%Y %H:%M:%S");
    print("[info] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=sys.stdout);

    if workspace_file_all:
        print("[info]  [" + now + "] " + " ".join(map(str,args)), **kwargs, file=workspace_file_all);
        workspace_file_all.flush();

    if workspace_file_stdout:
        print("[info]  [" + now + "] " + " ".join(map(str,args)), **kwargs, file=workspace_file_stdout);
        workspace_file_stdout.flush();

def warn(*args, **kwargs):
    global workspace_file_all;
    global workspace_file_stdout;
    global workspace_file_stderr;

    now = datetime.now().strftime("%d-%b-%Y %H:%M:%S");
    print("[WARN] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=sys.stdout);

    if workspace_file_all:
        print("[WARN] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=workspace_file_all);
        workspace_file_all.flush();

    if workspace_file_stderr:
        print("[WARN] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=workspace_file_stderr);
        workspace_file_stderr.flush();

def error(*args, **kwargs):
    global workspace_file_all;
    global workspace_file_stdout;
    global workspace_file_stderr;

    now = datetime.now().strftime("%d-%b-%Y %H:%M:%S");
    print("[ERROR] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=sys.stderr);

    if workspace_file_all:
        print("[ERROR] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=workspace_file_all);
        workspace_file_all.flush();

    if workspace_file_stderr:
        print("[ERROR] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=workspace_file_stderr);
        workspace_file_stderr.flush();

def fatal(*args, **kwargs):
    global workspace_file_all;
    global workspace_file_stdout;
    global workspace_file_stderr;

    now = datetime.now().strftime("%d-%b-%Y %H:%M:%S");
    print("[FATAL] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=sys.stderr);

    if workspace_file_all:
        print("[FATAL] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=workspace_file_all);
        workspace_file_all.flush();

    if workspace_file_stderr:
        print("[FATAL] [" + now + "] " + " ".join(map(str,args)), **kwargs, file=workspace_file_stderr);
        workspace_file_stderr.flush();

class Flag:
    def __init__(self, name, flags):
        self.state = 0;
        self.n_states = len(flags);
        self.exclusions = set();
        self.flags = flags;

        # For diagnostic and identification purposes only
        self.name = name;

    def __repr__(self):
        SHOW_FLAGS = True;

        if SHOW_FLAGS:
            return "<Flag {}: state={}, n_states={}, n_exclusions={}, {{{}}}>"\
                .format(self.name, self.state, self.n_states, len(self.exclusions),
                        " ".join(self.flags));
        else:
            return "<Flag {}: state={}, n_states={}, n_exclusions={}>"\
                .format(self.name, self.state, self.n_states, len(self.exclusions));

    def __str__(self):
        return self.flags[self.state];

    def all_states(self):
        return list([i for i in range(self.n_states)]);

    def valid_states(self):
        return list(filter(lambda s: s not in self.exclusions,
                           [i for i in range(self.n_states)]));

    def other_states(self):
        return list(filter(lambda s: s != self.state \
                           and s not in self.exclusions,
                           [i for i in range(self.n_states)]));

def fetch_gcc_version():
    res = subprocess.Popen([args.cc, "-v"],
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE);

    stdout, stderr = res.communicate();

    if res.returncode != 0:
        return None;

    lines = [line.strip() for line in stderr.decode("utf-8").split('\n') if len(line.strip()) > 0];

    # debug("Got lines:");
    # debug(lines);

    version_re = re.compile(r"gcc version ([0-9]+)\.([0-9]+)\.([0-9]+)");
    gcc_version = None;

    for line in lines:
        mo = version_re.search(line);
        if not mo:
            continue;

        gcc_version = (int(mo.group(1)),
                       int(mo.group(2)),
                       int(mo.group(3)));
        break;

    # debug("Got gcc version: {}".format(gcc_version));
    return gcc_version;

def fetch_gcc_target():
    res = subprocess.Popen([args.cc, "-v"],
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE);

    stdout, stderr = res.communicate();

    if res.returncode != 0:
        return None;

    lines = [line.strip() for line in stderr.decode("utf-8").split('\n') if len(line.strip()) > 0];

    # debug("Got lines:");
    # debug(lines);

    target_re = re.compile(r"Target: (\S+)");
    gcc_target = None;

    for line in lines:
        mo = target_re.search(line);
        if not mo:
            continue;

        gcc_target = mo.group(1);
        break;

    # debug("Got gcc target: {}".format(gcc_target));
    return gcc_target;

def fetch_gcc_params():
    params = {};

    gcc_version = fetch_gcc_version();
    if gcc_version is None:
        error("Failed to fetch GCC version");
        sys.exit(1);

    gcc_target = fetch_gcc_target();
    if gcc_target is None:
        error("Failed to fetch GCC version");
        sys.exit(1);

    info("GCC Appears to be version {}.{}.{}, targetting {}"\
         .format(gcc_version[0], gcc_version[1], gcc_version[2],
                 gcc_target));

    if gcc_version[0] > 9:
        re_param_bounded = re.compile(
            r"\-\-param\=([a-zA-Z0-9\-]+)\=<(\-?[0-9]+),(\-?[0-9]+)>\s+(\-?[0-9]+)");

        re_param_unbounded = re.compile(
            r"\-\-param\=([a-zA-Z0-9\-]+)\=\s+(\-?[0-9]+)");
    else:
        re_param_bounded = re.compile(
            r"([a-zA-Z0-9\-]+)\s+default (\-?[0-9]+) minimum (\-?[0-9]+) maximum (\-?[0-9]+)");

    res = subprocess.Popen([args.cc, "-Ofast", "--help=params", "-Q"],
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE);

    stdout, stderr = res.communicate();

    if res.returncode != 0:
        info("gcc exited with {}".format(res.returncode));
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
            if gcc_version[0] > 9:
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
        if gcc_version[0] < 10:
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
        print("line {}: Unrecognized parameter \"{}\""\
              .format(lineno, line), file=sys.stderr);

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

        "use-canonical-types"
    ];

    for to_remove in to_removes:
        if to_remove in params:
            del params[to_remove];

    # print("Got stdout:\n", "\n".join(lines));
    return params;

def fetch_gcc_optimizations():
    flags = [];

    re_param_simple = re.compile(r"\-f([a-zA-Z0-9\-]+)\s+(\[disabled\]|\[enabled\])?");

    res = subprocess.Popen([args.cc, "-Ofast", "--help=optimizers", "-Q"],
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE);

    stdout, stderr = res.communicate();

    if res.returncode != 0:
        error("[ERROR] gcc exited with {}".format(res.returncode));
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
            print("Found groups: {}".format(",".join([mo.group(i) for i in range(len(mo.groups()))])));
            # print("Found groups: {}".format(",".join([str(i) for i in range(10)])));
            flag_name = mo.group(1);

            # Remove flags which are hopefully irrelevant to speed
            # optimisation
            to_skip = [
                "live-patching",
                "ipa-profile",
                "profile-use",
                "profile-generate",
                "branch-probabilities",
                "auto-profile",
                "fexceptions"
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
        print("line {}: Unrecognized parameter \"{}\"".format(lineno, line), file=sys.stderr);

    # print("Got stdout:\n", "\n".join(lines));
    return flags;

def flatten_params(params):
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
            print("Expanding {}: (default: --param={}={})"\
                  .format(k, k, v["default"]), file=sys.stderr);

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

def fetch_all_gcc_flags():
    flags = [];
    
    # Everybody knows these
    # flags.append(Flag("-O", ["-O0", "-O1", "-O2", "-O3", "-Ofast", "-Os"]));

    # Fetch optimisation flags
    flags += fetch_gcc_optimizations();

    # Fetch parameters
    params = fetch_gcc_params();
    flags += flatten_params(params);

    return flags;

def fetch_target_gcc_flags():
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

def fetch_all_msvc_flags():
    return [
        "/O1",
        "/O2",
        "/Od",
        "/Og",
        "/Ot",
        "/Os",
        "/favor:blend",
        "/favor:AMD64",
        "/favor:INTEL64",
        "/favor:ATOM"
    ];

def fetch_all_cc_flags():
    if sys.platform.startswith('linux'):
        return fetch_all_gcc_flags();
    elif sys.platform == 'win32':
        return fetch_all_msvc_flags();

def check_cc_flag(flag):
    if sys.platform.startswith('linux'):
        return check_gcc_flag(flag);
    elif sys.platform == 'win32':
        return check_msvc_flag(flag);

def check_gcc_flag(flag):
    for state in flag.all_states():
        info("check_gcc_flag(): Checking {} variant of {} ({}/{})"\
             .format(flag.flags[state], flag.name, state, flag.n_states - 1));

        cmd = [args.cc,
               "-fno-diagnostics-color", # Don't leave control codes in stdout/stderr
               "-S", # It's not our responsibility to worry about the assembler or linker
               "-o", "/dev/null", # No output
               flag.flags[state],
               "-x", "c", # Must specify language if taking input from stdin
               "-" # Take input from stdin
               ];

        res = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            warn("Flag {} failed to compile, excluding".format(flag.flags[state]))
            flag.exclusions = flag.exclusions.union({state});

    return flag;

import tempfile;

def get_env_vc():
    BAT_SOURCE = """\
@echo off
call "{}" > NUL
set
""";

    if "comspec" not in os.environ:
        print("Failed to find comspec in environment, aborting");
        sys.exit(1);

    comspec = os.environ["comspec"];
    vcvarsall = r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat";

    file = tempfile.NamedTemporaryFile("w", suffix=".bat");
    # print("file: {}".format(file));

    with tempfile.TemporaryDirectory() as cwd:
        script = open(os.path.join(cwd, "get-env.bat"), "w");
        script.write(BAT_SOURCE.format(vcvarsall));
        
        cmd = [comspec,
               "/c",
               script.name];

        # Windows won't execute our script unless we close all open handles to it
        script.close();

        CREATE_NO_WINDOW = 0x08000000;

        run = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = run.communicate();

        if run.returncode != 0:
            print("Failed to execute \"{}\":".format(" ".join(cmd)));
            print(stderr.decode("utf-8"));
            sys.exit(1);

    # print("Got output:");
    # print(stdout.decode("utf-8"));
    # sys.exit(0);
    
    env_vc = dict();
    for line in stdout.decode("utf-8").split('\n'):
        line = line.strip();
        
        if len(line) == 0:
            continue;

        k, v = line.split('=', 1);
        env_vc[k] = v;

    return env_vc;

def check_msvc_flag(flag):
    test_c = "void f() { }\n";

    tempdir = tempfile.TemporaryDirectory();
    cwd = tempdir.name;

    test_filename = os.path.join(cwd, "main.c");
    with open(test_filename, "w") as file:
        file.write(test_c);

    cmd = [args.cc,
           "/c", # Compile only, no link
           flag,
           test_filename];

    res = subprocess.Popen(cmd, cwd=cwd,
                           stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE);

    stdout, stderr = res.communicate();

    debug("MSVC: Executed \"{}\", output:".format(" ".join(cmd)));
    debug("stdout:", stdout.decode("utf-8"));
    debug("stderr:", stderr.decode("utf-8"));

    return (flag, res.returncode);

# def read_flags_file(path):
#     flags = [];

#     with open(path, "r") as file:
#         lines = [line.strip() for line in file];

#     with mp.Pool() as pool:
#         results = pool.map(check_flag, lines);

#     for idx, result in enumerate(results):
#         returncode, stderr = result;
#         flag = lines[idx];

#         if returncode != 0:
#             print("[WARN]: Flag \"{}\" failed to compile with the following error:".format(flag), file=sys.stderr);
#             print(stderr);
#             continue;

#         flags.append(flag);

#     return flags;

# From here: https://stackoverflow.com/a/3431835
import hashlib

def hash_bytestr_iter(bytesiter, hasher, ashexstr=True):
    for block in bytesiter:
        hasher.update(block)
    return hasher.hexdigest() if ashexstr else hasher.digest()

def file_as_blockiter(afile, blocksize=65536):
    with afile:
        block = afile.read(blocksize)
        while len(block) > 0:
            yield block
            block = afile.read(blocksize)

def get_checksum_for_filename(filename):
    return hash_bytestr_iter(file_as_blockiter(open(filename, 'rb')), hashlib.sha256());

class CompileRequest:
    def __init__(self):
        pass;

import random;

class CompileResult:
    def __init__(self, ok, checksum):
        self.ok = ok;
        self.checksum = checksum;

class ExampleWorkerContext:
    MAIN_C = \
"""
#include <stdio.h>

#define ELEMS (1 << 10)

size_t elems = ELEMS;
struct { float x, y, z, w; } src[ELEMS], dst[ELEMS];

void work (void);

int
main (void)
{
  for (int i = 0; i < 1E6; ++i)
    work ();

  return 0;
}
""";

    WORK_C = \
"""
#include <stdio.h>

extern size_t elems;
extern struct { float x, y, z, w; } src[], dst[];

void
work (void)
{
  for (size_t i = 0; i < elems; ++i)
    dst[i] = src[i];
}
""";

    def __init__(self, idx, workspace):
        self.idx = idx;
        self.workspace = workspace;

        if sys.platform == 'win32':
            self.re_text_size = re.compile(r"\s*([0-9a-fA-F]+)\svirtual size");

        random.seed(self.idx);

    def init_workspace(self):
        debug("Worker #{}: Creating workspace in {}"\
              .format(self.idx, self.workspace));

        with open(os.path.join(self.workspace, "main.c"), "w") as file:
            file.write(self.MAIN_C);

        with open(os.path.join(self.workspace, "work.c"), "w") as file:
            file.write(self.WORK_C);

        if sys.platform == "win32":
            debug("Scraping Visual Studio environment variables...")
            self.env = get_env_vc();
        else:
            self.env = os.environ.copy();

        info("Worker #{}: Succesfully setup workspace".format(self.idx));
        return True;
    
    def better(x, y):
        # Return True if score `x` is better than score `y`
        return x < y;

    def worst_possible_result():
        # Return the worst possible result that is still
        # sortable. This is used internally to deal with tests that
        # fail, and thus should be pessimized as much as possible from
        # being selected to run again.
        return float('inf');

    def compile(self, flags):
        fstdout = open(os.path.join(self.workspace, "stdout.log"), "ab");
        fstderr = open(os.path.join(self.workspace, "stderr.log"), "ab");

        if sys.platform.startswith('linux'):
            cmd = [args.cc, "-Ofast", "-o", "work", "main.c", "work.c"] + flags;

        elif sys.platform == 'win32':
            cmd = [args.cc, "main.c", "work.c", "/Fe:work.exe"] + flags;

        else:
            error("Invalid platform for compile(): \"{}\""\
                  .format(sys.platform));
            return CompileResult(False, None);

        debug("Worker #{} [{}]: compile(): Executing \"{}\""\
              .format(self.idx, self.workspace, " ".join(cmd)));

        # for k, v in self.env.items():
        #     print("{}: {}".format(k, v));
        # print("INCLUDE: {}".format(self.env["INCLUDE"]))

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               env=self.env,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        fstdout.write(stdout);
        fstderr.write(stderr);

        fstdout.close();
        fstderr.close();

        if res.returncode != 0:
            error("Worker #{} [{}]: compile(): Exit code {}: Failed to compile:"\
                  .format(self.idx, self.workspace, res.returncode));
            print(stderr.decode("utf-8").strip());
            print(stdout.decode("utf-8").strip());
            return CompileResult(False, None);

        # Get the checksum
        checksum = get_checksum_for_filename(os.path.join(self.workspace, "work"));

        return CompileResult(True, checksum);

    def benchmark(self):
        return self.run();

    def run(self):
        if sys.platform.startswith('linux'):
            cmd = ["./work"];
        elif sys.platform == 'win32':
            cmd = ["work.exe"];

        debug("Worker #{} [{}]: run(): Executing \"{}\""\
              .format(self.idx, self.workspace, " ".join(cmd)));

        start = time.time();

        timeout_sec = 30;
        did_timeout_p = False;

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        try:
            stdout, stderr = res.communicate(timeout=timeout_sec);
        except subprocess.TimeoutExpired:
            did_timeout_p = True;

        if did_timeout_p:
            return None;

        if res.returncode != 0:
            return None;
        
        end = time.time();
        delta = end - start;

        return delta;

    def dumpbin_find_size_of_section(self):
        section = ".text";

        dumpbin = r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Tools\MSVC\14.28.29910\bin\Hostx64\x64\dumpbin.exe";
        cmd = [dumpbin, "/headers", "work.exe"];

        debug("Worker #{} [{}]: dumpbin_find_size_of_section(): Executing \"{}\""\
              .format(self.idx, self.workspace, " ".join(cmd)));

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               env=self.env,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            error("Worker #{}: Executing \"{}\" failed"\
                  .format(self.idx, " ".join(cmd)));
            return None;

        for line in stdout.decode("utf-8").split('\n'):
            # debug("dumpbin_find_size_of_section(): Scraping \"{}\"".format(line));
            mo = self.re_text_size.match(line);

            if not mo:
                continue;

            # debug("Found!");
            return int(mo.group(1), 16);

        error("Worker #{}: Failed to scrape section size for section \"{}\""\
              .format(self.idx, section));

    def size_find_size_of_section(self):
        cmd = ["size", "./work"];

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        lines = [line.strip() for line in stdout.decode("utf-8").split('\n')];
        fields = [field.strip() for field in lines[1].split()];

        text = int(fields[0]);
        data = int(fields[1]);
        bss = int(fields[2]);

        return float(text);

    def size(self):
        if sys.platform.startswith('linux'):
            return self.size_find_size_of_section();
        elif sys.platform == 'win32':
            return self.dumpbin_find_size_of_section();

class SweRVWorkerContext:
    def __init__(self, idx, workspace):
        self.idx = idx;
        self.workspace = workspace;

        self.env = os.environ.copy();
        self.env["RV_ROOT"] = self.workspace;

        self.re_ticks = re.compile(r"Total ticks      \: ([0-9]+)");

        self.march = "rv32imc";
        self.mabi = "ilp32";

    def init_workspace(self):
        debug("Worker #{}: Creating workspace in {}"\
              .format(self.idx, self.workspace));

        if "SWERV_SOURCE_TAR" not in os.environ:
            error("Worker #{}: Please set the environment variable \"SWERV_SOURCE_TAR\""
                  " to contain the path to a prebuilt Cores-SweRV.".format(self.idx));
            return False;

        self.SOURCE_TAR = os.environ["SWERV_SOURCE_TAR"];

        cmd = ["tar", "-xf", self.SOURCE_TAR,
               "--directory", self.workspace];
        
        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            error("[ERROR] Worker #{}: init_workspace(): Failed to extract:"\
                  .format(self.idx, file=sys.stderr));
            error(stderr.decode("utf-8").strip());
            return False;

        return True;
    
    def better(x, y):
        # Return True if score `x` is better than score `y`
        return x < y;

    def worst_possible_result():
        # Return the worst possible result that is still
        # sortable. This is used internally to deal with tests that
        # fail, and thus should be pessimized as much as possible from
        # being selected to run again.
        return float('inf');

    def compile(self, flags):
        clean = ["rm", "-f",
                 "cmark_iccm.dis",
                 "cmark_iccm.exe",
                 "cmark_iccm.map",
                 "cmark.o",
                 "crt0.cpp.s",
                 "crt0.o",
                 "printf.o",
                 "exec.log",
                 "program.hex"];

        res = subprocess.Popen(clean, cwd=self.workspace, env=self.env,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            error("Worker #{}: compile(): Failed to clean directory:"\
                  .format(self.idx));
            error(stderr.decode("utf-8").strip());
            return CompileResult(False, None);

        make = ["make", "-f", "tools/Makefile",
                "RV_ROOT={}".format(self.workspace),
                "GCC_PREFIX=riscv32-unknown-elf",
                "target=high_perf", "TEST=cmark_iccm",
                "TEST_CFLAGS={}".format(" ".join(["-march=" + self.march,
                                                  "-mabi=" + self.mabi,
                                                  "-Ofast"] + flags\
                                                 + ["-fno-exceptions", "-fno-asynchronous-unwind-tables"])),
                "program.hex"];

        debug("Worker #{}: compile(): Executing \"{}\""\
              .format(self.idx, " ".join(make)));

        res = subprocess.Popen(make, cwd=self.workspace, env=self.env,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            error("Worker #{} [{}]: compile(): Failed to compile:"\
                  .format(self.idx, self.workspace));
            error(stderr.decode("utf-8").strip());
            return CompileResult(False, None);

        # Get the checksum
        checksum = get_checksum_for_filename(os.path.join(self.workspace, "cmark_iccm.exe"));

        return CompileResult(True, checksum);

    def benchmark(self):
        return self.run();

    def run(self):
        make = ["make", "-f", "tools/Makefile",
                "RV_ROOT={}".format(self.workspace),
                "GCC_PREFIX=riscv32-unknown-elf",
                "target=high_perf", "TEST=cmark_iccm",
                "verilator"];

        debug("Worker #{}: run(): Executing \"{}\""\
              .format(self.idx, " ".join(make)));

        res = subprocess.Popen(make, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            warn("Failed to run:");
            warn(stderr.decode("utf-8"));
            return None;

        score = None;
        for line in stdout.decode("utf-8").split('\n'):
            line = line.strip();

            mo = self.re_ticks.match(line)
            if not mo:
                continue;

            score = int(mo.group(1));
        
        if score is None:
            warn("Failed to run");
        else:
            debug("Worker #{}: [{}]: run(): Got score \"{}\""\
                  .format(self.idx, self.workspace, str(score)));

        return score;

    def size(self):
        cmd = ["riscv32-unknown-elf-size", "./cmark_iccm.exe"];

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        # debug("size stdout: ", stdout);
        # debug("size stderr: ", stderr);

        lines = [line.strip() for line in stdout.decode("utf-8").split('\n')];
        fields = [field.strip() for field in lines[1].split()];

        text = int(fields[0]);
        data = int(fields[1]);
        bss = int(fields[2]);

        return text;

def worker_func(worker_ctx, work_queue, result_queue, binary_checksum_result_cache):
    idx = worker_ctx.idx;
    debug("Worker #{}: Started".format(idx));
    
    while True:
        job = work_queue.get(block=True);

        if job is None:
            debug("Worker #{}: Exiting".format(idx));
            return;

        flags, state_variation = job;
        flags_str = " ".join(flags)

        if state_variation is None:
            debug("Worker #{}: Got job with state variation (<None>), flags \"{}\""\
                  .format(idx, flags_str));
        else:
            debug("Worker #{}: Got job with state variation ({}, {}), flags \"{}\""\
                  .format(idx, state_variation[0], state_variation[1], flags_str));

        compile_result = worker_ctx.compile(flags);
        if compile_result.ok:
            debug("Worker #{}: Succesfully compiled with flags \"{}\"".format(idx, flags_str));
            checksum = compile_result.checksum;

        else:
            warn("Worker #{}: Failed to compile with flags \"{}\"".format(idx, flags_str));
            # Can't benchmark what we can't build: return.
            result_queue.put((flags, state_variation, None), block=False);
            continue;

        if checksum in binary_checksum_result_cache:
            score = binary_checksum_result_cache[checksum];
            debug("Worker #{}: Hit cache result \"{}\"! Re-using result {}"\
                  .format(idx, checksum, score));

            result = (flags, state_variation, score);
            result_queue.put(result, block=False);
            continue;

        score = worker_ctx.benchmark();
        if score is not None:
            debug("Worker #{}: Succesful benchmark, got score {} with flags \"{}\""\
                  .format(idx, str(score), flags_str));
            binary_checksum_result_cache[checksum] = score;

        else:
            warn("Worker #{}: Failed to benchmark with flags \"{}\"".format(idx, flags_str));

        result = (flags, state_variation, score);
        result_queue.put(result, block=False);

def create_cmd_from_flaglist(flaglist):
    return [str(flag) for flag in flaglist];

def work():
    global args;

    if args.flag_baselines_file is not None:
        info("Will be using \"{}\" for flag baselines"\
             .format(args.flag_baselines_file));
    else:
        info("No flag baselines file specified, will automatically generate flag baselines");

    if args.cc is not None:
        info("Will be using \"{}\" for flag baselines"\
             .format(args.cc));
    else:
        info("No C compiler specified, will use whatever is in path");

    # The WorkerContext class that we will be using
    if args.context is None:
        warn("No worker context specified, using ExampleWorkerContext");
        worker_context_classname = "ExampleWorkerContext";
    else:
        worker_context_classname = args.context;

    WorkerContext = getattr(sys.modules[__name__], worker_context_classname)

    if WorkerContext is None:
        error("Unknown WorkerContext classname: \"{}\"".\
              format(worker_context_classname));
        sys.exit(1);

    n_tests = 0;

    if args.processes is not None:
        n_core_count = args.processes;
    else:
        n_core_count = mp.cpu_count();

    info("Running with {} processes".format(n_core_count));

    # Global leaderboard to record _all_ results
    global_leaderboard = [];

    # "active" leaderboard, which only records flags whose score was an
    # improvement on their parent flag's score.
    leaderboard = [];

    # The current best result on the leaderboard
    best_flagpath = None;

    work_queue = mp.Queue();
    result_queue = mp.Queue();

    ### Phase 1: Flag discovery
    # Before we go and run the "real" search routine, first we find
    # out what each flag does individually, what impact it has, and if
    # it works at all.
    flags = [];
    all_cc_flags = fetch_all_cc_flags();

    for i, flag in enumerate(all_cc_flags):
        print("flag {}: {}".format(i, repr(flag)));

    # sys.exit(0);

    # Load target flags, if any
    all_cc_flags += fetch_target_gcc_flags();

    # Trim flags (useful for debug)
    # all_cc_flags = all_cc_flags[-20:-1];

    with mp.Pool(n_core_count) as pool:
        all_cc_flags = pool.map(check_cc_flag, all_cc_flags);

    # for i, flag in enumerate(all_cc_flags):
    #     print("flag {}: {}".format(i, repr(flag)));

    # Now, all_cc_flags may have excluded flags (because they
    # miscompiled.) It is not impossible that some flags had every
    # state excluded, and such flags we should simply remove from
    # consideration.

    len_all_cc_flags_before = sum([flag.n_states for flag in all_cc_flags]);
    all_cc_flags = list(filter(lambda cc_flag: cc_flag.n_states > len(cc_flag.exclusions),
                               all_cc_flags));
    len_all_cc_flags_after = sum([flag.n_states - len(flag.exclusions) for flag in all_cc_flags]);

    info("flags before excluding broken flags: {} entries.".format(len_all_cc_flags_before));
    info("flags after excluding broken flags: {} entries.".format(len_all_cc_flags_after));

    # Fixup the flag initial state. We want to pick state 0 as much as
    # possible, but if that became an exluded state after being tested, then we need to update it.
    for flag in all_cc_flags:
        flag.state = flag.valid_states()[0];

    flags = all_cc_flags;

    if len(flags) == 0:
        error("After testing \"{}\" flags for function, we're left with 0"
              " working flags! Maybe you're missing the C compiler or something?");
        sys.exit(1);

    # sys.exit(0);

    ### Create the worker contexts

    simpletuner_directory = os.path.join(os.getcwd(), 'workspace');

    if os.path.isdir(simpletuner_directory):
        info("Reusing simpletuner directory \"{}\""\
              .format(simpletuner_directory));
    else:
        try:
            os.mkdir(simpletuner_directory);
        except:
            error("Failed to create top-level simpletuner directory \"{}\""\
                  .format(simpletuner_workspace));
            sys.exit(1);

    # Create a unique run directory
    random_suffix = "".join(
        [random.choice(string.ascii_letters + "0123456789") for _ in range(4)]);

    run_directory \
        = os.path.join(
            simpletuner_directory,
            datetime.now().strftime("%Y%m%d-%H%M%S-" + random_suffix));

    if os.path.isdir(run_directory):
        error("You're either seriously unlucky, or something is "
              "seriously amiss: Run directory \"{}\" already exists"\
              .format(run_directory));
        sys.exit(1);

    os.mkdir(run_directory);

    # Create log files
    global workspace_file_all;
    workspace_file_all = open(os.path.join(run_directory, "all.log"), "w");
    global workspace_file_stdout;
    workspace_file_stdout = open(os.path.join(run_directory, "stdout.log"), "w");
    global workspace_file_stderr;
    workspace_file_stderr = open(os.path.join(run_directory, "stderr.log"), "w");

    # Create worker directories, and then the workers themselves.
    worker_ctxs = [];
    for idx in range(n_core_count):
        worker_workspace = os.path.join(run_directory, str(idx));

        os.mkdir(worker_workspace);
        worker_ctxs.append(WorkerContext(idx, worker_workspace));

    # Create shared dictionary mapping checksums to run times. This
    # avoids having to run binaries for which the result didn't
    # change.
    manager = mp.Manager();
    binary_checksum_result_cache = manager.dict();

    debug("Creating {} workers".format(n_core_count));
    workers = [mp.Process(target=worker_func,
                          args=(worker_ctx, work_queue, result_queue, binary_checksum_result_cache))
               for worker_ctx in worker_ctxs];
    debug("Done creating {} workers".format(n_core_count));

    init_workspaces_ok = [];
    for worker_ctx in worker_ctxs:
        init_workspaces_ok.append(worker_ctx.init_workspace());

    if any([not ok for ok in init_workspaces_ok]):
        error("Atleast one workspace failed to initialize its workspace directory, aborting");
        sys.exit(1);

    # If the user called us with "--setup-workspace-only", we are
    # done.
    if args.setup_workspace_only:
        sys.exit(0);

    for idx, worker in enumerate(workers):
        debug("Starting Worker #{}".format(idx));
        worker.start();

    debug("Started {} workers".format(n_core_count));

    f_live_global_leaderboard = open(
        os.path.join(run_directory, "global_leaderboard.live"), "w");

    # sys.exit(0);

    n_iterations = 0;

    ### Enter main loop:
    while True:
        debug("Running iteration {}".format(n_iterations));

        # First, get the baseline for the current flag configuration
        work_queue.put((create_cmd_from_flaglist(flags), None), block=False);
        result = result_queue.get(block=True);

        _, _, score = result;

        if score is None:
            fatal("Failed to get baseline for configuration \"{}\"".format("fixme"));
            sys.exit(1);

        baseline = score;

        # Instantiate all the jobs we're working on
        state_variation_and_scores = [];
        n_jobs = 0;

        for flag_idx, flag in enumerate(flags):
            for other_state in flag.other_states():
                state_variation = (flag_idx, other_state)
                state_variation_and_scores.append((state_variation, None));

                state_variation_flags = copy.deepcopy(flags);
                state_variation_flags[flag_idx].state = other_state;

                work_queue.put((create_cmd_from_flaglist(state_variation_flags),
                                state_variation),
                               block=False);
                n_jobs += 1;

        # It may be the case that we've reached the end of
        # state_variations (all have been excluded but one). In which
        # case we are done.
        if n_jobs == 0:
            info("Did not find any state variations to test: We are done.");
            break;

        # Wait for the results
        while n_jobs > 0:
            result = result_queue.get(block=True);
            n_jobs -= 1;

            job_flags, state_variation, score = result;

            if score is None:
                score = float('inf');

            flag_idx, other_state = state_variation;

            # Save to file
            print("{},{}".format(" ".join(job_flags), score),
                  file=f_live_global_leaderboard);
            f_live_global_leaderboard.flush();

            # print("state_variation_and_scores: {}".format(state_variation_and_scores));
            # print("looking for: {}, {}".format(flag_idx, other_state));

            idxes = [i for i, e in enumerate(state_variation_and_scores) if e[0][0] == flag_idx and e[0][1] == other_state];
            # debug("idxes: {}".format(idxes));

            state_variation_and_scores[idxes[0]] = (state_variation, score);

        # Now sort the list, with best state variation at the top and
        # worst the worst at the bottom.
        state_variation_and_scores.sort(key=lambda e: e[1]);

        # Write out to file for debugging
        with open(os.path.join(run_directory, "iteration.{}".format(n_iterations)), "w") as file:
            print("current flags: {}".format(" ".join(job_flags)), file=file);
            print("baseline: {}".format(baseline), file=file);

            print("State variations:", file=file);

            for state_variation, score in state_variation_and_scores:
                flag_idx, state = state_variation;
                print("{},{}".format(flags[flag_idx].flags[state], score), file=file);

        # Now, we can do something to the baseline set of flags with
        # this information.

        # ...If noone beat the baseline, then actually we don't have any more work to do.
        have_better_than_baseline_p = False;
        for state_variation, score in state_variation_and_scores:
            if score < baseline:
                have_better_than_baseline_p = True;
                break;

        if not have_better_than_baseline_p:
            info("Iteration {}: No state variable variation managed to beat the current baseline of {}: Exiting."\
                 .format(n_iterations, baseline));
            break;

        # Exclude some flags from the worst states.
        MAX_EXCLUSIONS = 1;
        to_exclude = min(MAX_EXCLUSIONS, len(state_variation_and_scores));

        for state_variation, score in state_variation_and_scores[-to_exclude:]:
            flag_idx, other_state = state_variation;
            flags[flag_idx].exclusions = flags[flag_idx].exclusions.union({other_state});

        # Promote some flags to the best states.
        MAX_PROMOTIONS = 1;
        to_promote = min(MAX_PROMOTIONS, len(state_variation_and_scores));
        have_promoted = [];

        for state_variation, score in state_variation_and_scores[0 : to_promote]:
            flag_idx, other_state = state_variation;

            # We don't want to re-promote a flag index that we've
            # already promoted - that would be a de-motion!
            if flag_idx in have_promoted:
                continue;

            have_promoted.append(flag_idx);

            # We don't want to go back to the old state... or do we?
            current_state = flags[flag_idx].state;
            flags[flag_idx].exclusions = flags[flag_idx].exclusions.union({current_state});
            flags[flag_idx].state = other_state;

        # Now that we've adjusted the current flag state, go to the next iteration.
        n_iterations += 1;

    # If we're here, we broke out of the loop because we have no more
    # work to do. Close workers, close queues, and exit.
    for idx, worker in enumerate(workers):
        work_queue.put(None);

    for idx, worker in enumerate(workers):
        debug("Trying to exit Worker #{}...".format(idx));
        worker.join();
        debug("Exited Worker #{}".format(idx));

    work_queue.close();
    result_queue.close()

    info("All done, tested {} flag combinations."\
          .format(n_tests));

    f_final_global_leaderboard = open(
        os.path.join(run_directory, "global_leaderboard.final"), "w");

    # info("Global leaderboard:");
    # for flagpath in global_leaderboard:
    #     info("\t{},{}".format(" ".join(flagpath), lookup_flag_from_flagpath(root, flagpath).score));
    #     print("{},{}".format(" ".join(flagpath), lookup_flag_from_flagpath(root, flagpath).score),
    #           file=f_final_global_leaderboard);

    #     f_final_global_leaderboard.flush();

    f_final_global_leaderboard.close();
    f_live_global_leaderboard.close();

def test_worker_context():
    wc = WorkerContext(0, os.path.join(os.getcwd(), 'workspace', '0'));
    wc.init_workspace();
    wc.compile([]);
    wc.size();

def main():
    work();

if __name__ == "__main__":
    main();
