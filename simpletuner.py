#!/usr/bin/env python3
import os, sys, re, time, random, subprocess, shutil, string;
from datetime import datetime;

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

parser.add_argument("--cc-for-discovery", default=None,
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

CC = "gcc";
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

def fetch_gcc_version():
    res = subprocess.Popen([CC, "-v"],
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
    res = subprocess.Popen([CC, "-v"],
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

    res = subprocess.Popen([CC, "--help=params", "-Q"],
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

    re_param_simple = re.compile(r"\-f([a-zA-Z0-9\-]+)\s+");

    res = subprocess.Popen([CC, "--help=optimizers", "-Q"],
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
            # print("Found groups: {}".format(",".join([mo.group(i) for i in range(len(mo.groups()))])));
            # print("Found groups: {}".format(",".join([str(i) for i in range(10)])));
            flag_name = mo.group(1);

            # print("line {}: Parsed parameter \"{}\", range [{},{}], default {}"\
            #       .format(lineno, param_name, param_range[0], param_range[1],
            #               param_default));
            flags.append("-f" + flag_name);
            flags.append("-fno-" + flag_name);

            continue;

        # If we're still here, it may be because we got a strange
        # flag, e.g.
        #
        #   -fvect-cost-model=[unlimited|dynamic|cheap|very-cheap]        [default]
        # or
        #     -flifetime-dse=<0,2>                  2
        print("line {}: Unrecognized parameter \"{}\"".format(lineno, line), file=sys.stderr);

    # Remove flags which are hopefully irrelevant to speed
    # optimisation
    to_removes = [
    ];

    for to_remove in to_removes:
        try:
            flags.remove(to_remove);
        except ValueError:
            continue;

    # print("Got stdout:\n", "\n".join(lines));
    return flags;

def flatten_params(params):
    flags = [];

    for k, v in params.items():
        if v["min"] is None:
            # print("Skipping {} as it is unbounded".format(k), file=sys.stderr);
            # continue;
            pass;

        else:
            print("Expanding {}: (default: --param={}={})"\
                  .format(k, k, v["default"]), file=sys.stderr);

        # Treat the unbounded parameters specially
        unbounded_p = v["min"] == 0 and v["max"] == 2147483647;

        n_options = v["max"] - v["min"] + 1;

        if unbounded_p:
            if v["default"] == 0:
                for i in range(0, 101, 5):
                    flags.append("--param={}={}".format(k, i));

            else:
                half_range = v["default"];
                full_range = half_range * 2;
                for i in range(0, full_range + 1,
                               full_range // 10 if full_range >= 10 else 1):
                    flags.append("--param={}={}".format(k, i));

            continue;

        if n_options <= 25:
            for i in range(v["min"], v["max"] + 1):
                flags.append("--param={}={}".format(k, i));
        else:
            # `... v["max"]` is correct - do the `v["max"] + 1` case
            # explicitly, so we can guarantee to always test it

            for i in range(v["min"], v["max"], n_options // 10):
                flags.append("--param={}={}".format(k, i));

            # Make sure we always test the maximum value
            flags.append("--param={}={}".format(k, v["max"]));

    return flags;

def fetch_all_gcc_flags():
    flags = [];
    
    # Fetch parameters
    params = fetch_gcc_params();
    flags += flatten_params(params);

    # Fetch optimisation flags
    flags += fetch_gcc_optimizations();

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
    cmd = [CC,
           "-fno-diagnostics-color", # Don't leave control codes in stdout/stderr
           "-S", # It's not our responsibility to worry about the assembler or linker
           "-o", "/dev/null", # No output
           flag,
           "-x", "c", # Must specify language if taking input from stdin
           "-" # Take input from stdin
           ];

    res = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE);

    stdout, stderr = res.communicate();

    return (flag, res.returncode);

import tempfile;

def check_msvc_flag(flag):
    test_c = "void f() { }\n";

    tempdir = tempfile.TemporaryDirectory();
    cwd = tempdir.name;

    test_filename = os.path.join(cwd, "main.c");
    with open(test_filename, "w") as file:
        file.write(test_c);

    cmd = [CC,
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

class ExampleWorkerContext:
    MAIN_C = \
"""
#include <stdlib.h>
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
#include <stddef.h>

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

    def init_workspace(self):
        debug("Worker #{}: Creating workspace in {}"\
              .format(self.idx, self.workspace));

        with open(os.path.join(self.workspace, "main.c"), "w") as file:
            file.write(self.MAIN_C);

        with open(os.path.join(self.workspace, "work.c"), "w") as file:
            file.write(self.WORK_C);

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
        if sys.platform.startswith('linux'):
            cmd = [CC, "-Ofast", "-o", "work", "main.c", "work.c"] + flags;

        elif sys.platform == 'win32':
            cmd = [CC, "main.c", "work.c", "/Fe:work.exe"] + flags;

        debug("Worker #{} [{}]: compile(): Executing \"{}\""\
              .format(self.idx, self.workspace, " ".join(cmd)));

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            error("Worker #{} [{}]: compile(): Exit code {}: Failed to compile:"\
                  .format(self.idx, self.workspace, res.returncode));
            print(stderr.decode("utf-8").strip());
            return False;

        return True;

    def benchmark(self):
        return self.size();

    def run(self):
        if sys.platform.startswith('linux'):
            cmd = ["./work"];
        elif sys.platform == 'win32':
            cmd = ["work.exe"];

        start = time.time();
        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        end = time.time();
        delta = end - start;

        if res.returncode != 0:
            return None;
        
        return delta;

    def dumpbin_find_size_of_section(self):
        section = ".text";

        cmd = ["dumpbin.exe", "/headers", "work.exe"];

        res = subprocess.Popen(cmd, cwd=self.workspace,
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
            return False;

        make = ["make", "-f", "tools/Makefile",
                "RV_ROOT={}".format(self.workspace),
                "GCC_PREFIX=riscv32-unknown-elf",
                "target=high_perf", "TEST=cmark_iccm",
                "TEST_CFLAGS={}".format(" ".join(["-march=" + self.march,
                                                  "-mabi=" + self.mabi,
                                                  "-Ofast"] + flags)),
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
            return False;

        return True;

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

class Flag:
    def __init__(self, flag, flags):
        self.flags = flags;
        self.flag = flag;
        self.score = None;
        self.children = dict();

    def __str__(self):
        return "" if self.flag is None else self.flag;

    def create_iterator(self):
        items = list(filter(lambda flag: (flag not in self.children or \
                                          self.children[flag].score is None), self.flags));

        if self.flag is None:
            return iter(items);

        idx = self.flags.index(str(self));
        return iter(items[idx+1:]);

def lookup_parent_flag_from_flagpath(root, flagpath):
    assert(isinstance(flagpath, list));
    
    if len(flagpath) == 0:
        return None;
    
    elif len(flagpath) < 2:
        if flagpath[0] not in root.children:
            walker.children[flagpath[0]] = Flag(flagpath[0], root.flags);

        if len(flagpath) == 1:
            return root;
    
    parent = root;
    child = parent.children[flagpath[0]];

    for flag in flagpath[1:]:
        if flag not in child.children:
            child.children[flag] = Flag(flag, root.flags);

        parent = child;
        child = child.children[flag];

    return parent;

def lookup_flag_from_flagpath(root, flagpath):
    assert(isinstance(flagpath, list));
    
    if len(flagpath) == 0:
        return root;

    walker = root;

    for flag in flagpath:
        if flag not in walker.children:
            walker.children[flag] = Flag(flag, root.flags);

        walker = walker.children[flag];

    return walker;

def worker_func(worker_ctx, work_queue, result_queue):
    idx = worker_ctx.idx;
    debug("Worker #{}: Started".format(idx));
    
    while True:
        job = work_queue.get(block=True);

        if job is None:
            debug("Worker #{}: Exiting".format(idx));
            return;

        flagpath = job;
        flags = " ".join(flagpath)
        debug("Worker #{}: Got job with flags \"{}\"".format(idx, flags));

        compile_ok = worker_ctx.compile(flagpath);
        if compile_ok:
            debug("Worker #{}: Succesfully compiled with flags \"{}\"".format(idx, flags));
        else:
            warn("Worker #{}: Failed to compile with flags \"{}\"".format(idx, flags));
            # Can't benchmark what we can't build: return.
            result_queue.put((flagpath, None), block=False);
            continue;

        score = worker_ctx.benchmark();
        if score is not None:
            debug("Worker #{}: Succesful benchmark, got score {} with flags \"{}\""\
                  .format(idx, str(score), flags));
        else:
            warn("Worker #{}: Failed to benchmark with flags \"{}\"".format(idx, flags));

        result = (flagpath, score);
        result_queue.put(result, block=False);

def create_job_from_flagpath(flagpath):
    return flagpath;

def work():
    global args;
    global CC;

    args = parser.parse_args();

    if args.flag_baselines_file is not None:
        info("Will be using \"{}\" for flag baselines"\
             .format(args.flag_baselines_file));
    else:
        info("No flag baselines file specified, will automatically generate flag baselines");

    if args.cc_for_discovery is not None:
        info("Will be using \"{}\" for flag baselines"\
             .format(args.cc_for_discovery));
        CC = args.cc_for_discovery;
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

    # All flags under consideration
    # flags = ["a", "b", "c", "d"];
    # flags = read_flags_file("/home/maxim/prj/opentuner/ssv2/flags");

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

    # If we were provided any target flags, append them now.
    if args.target_flags_file is not None:
        with open(args.target_flags_file) as target_flags_file:
            for line in target_flags_file:
                line = line.strip();

                if len(line) == 0:
                    continue;

                debug("Appending target flag \"{}\"".format(line));
                flags.append(line);

    # all_gcc_flags = all_gcc_flags[-20:-1];

    with mp.Pool(n_core_count) as pool:
        all_cc_flags_test_results = pool.map(check_cc_flag, all_cc_flags);

    for flag, returncode in all_cc_flags_test_results:
        if returncode == 0:
            flags.append(flag);

    if len(flags) == 0:
        error("After testing \"{}\" flags for function, we're left with 0"
              " working flags! Maybe you're missing the C compiler or something?");
        sys.exit(1);

    ### Phase 2: Flag performance measurement
    # We need to create the workers anyway...

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

    worker_ctxs = [];
    for idx in range(n_core_count):
        worker_workspace = os.path.join(run_directory, str(idx));

        os.mkdir(worker_workspace);
        worker_ctxs.append(WorkerContext(idx, worker_workspace));

    debug("Creating {} workers".format(n_core_count));
    workers = [mp.Process(target=worker_func,
                          args=(worker_ctx, work_queue, result_queue))
               for worker_ctx in worker_ctxs];
    debug("Done creating {} workers".format(n_core_count));

    with mp.Pool(n_core_count) as pool:
        init_workspaces_ok = pool.map(WorkerContext.init_workspace, worker_ctxs);

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

    flags_file = args.flag_baselines_file;

    if not flags_file:
        # Now test individually all the flags that we've discovered.
        n_active_jobs = 0;
        results = [];

        for flag in flags:
            debug("putting {} on work queue...".format(flag));
            work_queue.put([flag]);
            n_active_jobs += 1;

        while n_active_jobs > 0:
            flagpath, score = result_queue.get(block=True);
            n_active_jobs -= 1;
            info("{} flag tests left".format(n_active_jobs));

            if score is None:
                score = WorkerContext.worst_possible_result();

                # if WorkerContext.better(0.0, float('-inf')):
                #     score = float('-inf');
                # else:
                #     score = float('inf');

            results.append((flagpath[0], score));

        # If `better` performance is lower numbers, sort ascending. otherwise,
        # sort descending. First element should be best performing.
        results.sort(key=lambda e: e[1], reverse=WorkerContext.better(2, 1));

        flags = [flag for flag, score in results];

        # Root flag from which we will be searching
        root = Flag(None, flags);

        # Also, create and set the child scores, since we've already
        # calculated them for the baselines.
        for flag, score in results:
            flagpath = [flag];

            child = lookup_flag_from_flagpath(root, flagpath);
            child.score = score;

    else:
        results = [];

        debug("Processing flags file \"{}\"..."\
              .format(flags_file));

        with open(flags_file, "r") as flags_top:
            for line in flags_top:
                line = line.strip();
                debug("Processing line \"{}\"".format(line));
                flag, score = line.split(',');
                score = float(score);

                if score == WorkerContext.worst_possible_result():
                    debug("Found bad result, omitting from results");
                    continue;

                results.append((flag, score));
        
        results.sort(key=lambda e: e[1], reverse=WorkerContext.better(2, 1));

        flags = [flag for flag, score in results];

        # Root flag from which we will be searching
        root = Flag(None, flags);

        # Also, create and set the child scores, since we've already
        # calculated them for the baselines.
        for flag, score in results:
            flagpath = [flag];

            child = lookup_flag_from_flagpath(root, flagpath);
            child.score = score;

    # Regardless of whether or not we generated the top flags file
    # manually, we always write it out to our run directory.
    flags_file = os.path.join(run_directory, "flags.top");
    with open(flags_file, "w+") as flags_top:
        for flag, score in results:
            print("{},{}".format(flag, score), file=flags_top);

            # Also add it to the global leaderboard
            global_leaderboard.append([flag])

    # Submit root flag for testing
    job = create_job_from_flagpath([]);
    info("Putting first job on queue");
    info("root flags: {}".format(root.flags));
    work_queue.put(job, block=False);
    n_active_jobs = 1;
    n_tests = 1;

    debug("Put one job on the queue \"{}\"".format(job));

    flagpath, score = result_queue.get(block=True);
    n_active_jobs -= 1;

    debug("Root: got score \"{}\" (type {})".format(score, type(score)));

    if score is None:
        fatal("root test failed");
        for worker in workers:
            worker.terminate();

        sys.exit(1);

    # Make sure to record the root flag on the global leaderboard (it
    # may be the case that the root flag is the only flag worth
    # running, if all the root flag's children have a worse score than
    # their parent.
    global_leaderboard.append(flagpath);

    # ...However, we do _not_ put the root flag on the `leaderboard`,
    # because by definition all of its children will have been
    # considered, and thus it is no longer eligible for exploitation.

    debug("root.score = {}".format(score));
    root.score = score;

    # Now that we have a root score, populate the leaderboard if the
    # score of the given child is `better` than that of the root
    # score.
    for child_flag in root.flags:
        child = root.children[child_flag];

        if WorkerContext.better(child.score, root.score):
            debug("Leaderboard init: child \"{}\" score {} is better "
                  "than root score of {}, adding to leaderboard"\
                  .format(child_flag, child.score, root.score));

            flagpath = [child_flag];
            leaderboard.append(flagpath)
        else:
            debug("Leaderboard init: child \"{}\" score {} is not better "
                  "than root score of {}, adding to leaderboard"\
                  .format(child_flag, child.score, root.score));

    leaderboard.sort(key=lambda flagpath: lookup_flag_from_flagpath(root, flagpath).score);
    debug("Leaderboard now:");
    for flagpath in leaderboard:
        print(" ".join(flagpath));

    f_live_global_leaderboard = open(
        os.path.join(run_directory, "global_leaderboard.live"), "w");

    ### Enter main loop:
    while True:
        # We're done
        if n_active_jobs == 0 \
           and len(leaderboard) == 0:
            # We have no more work to do
            debug("No more work: Exiting...");
            
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

            info("Global leaderboard:");
            for flagpath in global_leaderboard:
                info("\t{},{}".format(" ".join(flagpath), lookup_flag_from_flagpath(root, flagpath).score));
                print("{},{}".format(" ".join(flagpath), lookup_flag_from_flagpath(root, flagpath).score),
                      file=f_final_global_leaderboard);

                f_final_global_leaderboard.flush();

            f_final_global_leaderboard.close();
            f_live_global_leaderboard.close();

            break;

        # We may have to block on the result queue, if:
        # 1) All execution threads have been given a job, and we need
        #    to wait for atleast one to return a result before we can
        #    submit more jobs.
        # 2) We've submitted all as-of-yet untested children.
        #    (`leaderboard` will be empty if all the current known
        #    flags have had all their children submitted for testing.)
        elif n_active_jobs == n_core_count \
           or len(leaderboard) == 0:
            result = result_queue.get(block=True);

        # Non-blocking read, for when we're not too fussed about
        # getting a result right now, because we will (probably) have
        # work items we can put anyway.
        else:
            try:
                result = result_queue.get_nowait();
            except queue.Empty:
                result = None;

        if result is not None:
            n_active_jobs -= 1;
            n_tests += 1;

            flagpath, score = result;

            # All we are responsible for doing here is updating the
            # score in the tree, and updating the leaderboard (if the
            # score is better than the parent.)
            flag = lookup_flag_from_flagpath(root, flagpath);
            if score is not None:
                flag.score = score;

            else:
                # This indicates that the test failed. So we want to
                # give it the most pessimistic score possible, being
                # either -inf or inf - work out which.
                flag.score = WorkerContext.worst_possible_result();

                # if WorkerContext.better(0.0, float('-inf')):
                #     flag.score = float('-inf');
                # else:
                #     flag.score = float('inf');

            parent_flag = lookup_parent_flag_from_flagpath(root, flagpath);
            # debug("Got parent_flag \"{}\" for flagpath \"{}\"".format(parent_flag, flagpath));

            # Special case: if `flagpath` is `[]` (i.e. we have
            # received the result for testing the `root` flag), then
            # we have no `parent_flag`, and we by-definition put it on
            # the `leaderboard` (which by-defintion must be empty at
            # this point.)
            if parent_flag is None:
                leaderboard.append([]);
                # debug("L164: Leaderboard: {}".format(leaderboard));

            else:
                if WorkerContext.better(flag.score, parent_flag.score):
                    # FIXME: sorted insert
                    leaderboard.append(flagpath);
                    leaderboard.sort(key=lambda path: lookup_flag_from_flagpath(root, path).score);
                    # debug("Added \"{}\" to leaderboard".format(flagpath));
                else:
                    # debug("Child flag \"{}\" ({}) is not better than \"{}\" ({}), skipping"\
                    #       .format(flagpath, flag.score, flagpath[:-1], parent_flag.score));
                    pass;

            # Always store the result in the `global_leaderboard`
            # FIXME: sorted insert
            if len(global_leaderboard) > 0:
                prev_best_score = global_leaderboard[0];
            else:
                prev_best_score = None;

            global_leaderboard.append(flagpath);
            global_leaderboard.sort(key=lambda path: lookup_flag_from_flagpath(root, path).score);

            curr_best_score = global_leaderboard[0];

            if curr_best_score != prev_best_score:
                info("New best flag: \"{}\", score {}"\
                     .format(" ".join(best_flagpath), best_flag.score));

            # Also write it out to the live leaderboard file, incase
            # we crash or something.
            print(" ".join(flagpath) + ","\
                  + str(lookup_flag_from_flagpath(root, flagpath).score),
                  file=f_live_global_leaderboard);
            f_live_global_leaderboard.flush();

        # Pick best from leaderboard
        # NOTE: If leaderboard is empty, that just means that:
        #   1). we have exhausted whatever parents we had, AND
        #   2). all of their children that have been scheduled have either
        #       resolved and failed to beat the parent, or haven't resolved yet.
        # if thats the case, then we just need to go back up and blocking-wait.
        if len(leaderboard) == 0:
            continue;
        
        current_best_flagpath = leaderboard[0];

        # If the best flag is now different, switch to exploring it instead.
        if best_flagpath != current_best_flagpath:
            best_flagpath = current_best_flagpath;
            best_flag = lookup_flag_from_flagpath(root, best_flagpath);
            best_flag_children_iterator = best_flag.create_iterator();

        # Get next job
        have_next_flag_p = False;
        try:
            next_child_flag = next(best_flag_children_iterator);
            have_next_flag_p = True;
            
        except StopIteration:
            # We have exhausted the `best_flag`'s immediate search space
            # (but not neccesarily its children's children search space).
            # Remove the flag this flag iterator belongs to from the
            # leaderboard.

            leaderboard.remove(best_flagpath);
            # debug("Removed \"{}\" from leaderboard as it is exhausted"\
            #       .format(best_flagpath));

            # debug("Leaderboard now:");
            for item in leaderboard:
                print("\t" + str(item));
            
            # At this point, go back up and loop again. P.S. if leaderboard is empty now,
            # then we'll block on the next iteration.
            continue;

        # If we're here, we got a `next_child_flag`.
        # debug("next_child_flag: {}".format(best_flagpath + [next_child_flag]));
        
        # We must have spare compute capacity here, otherwise we would have
        # blocked at the very beginning.
        if have_next_flag_p:
            job = create_job_from_flagpath(best_flagpath + [next_child_flag]);
            work_queue.put(job);
            n_active_jobs += 1;

        # We're done, go back up.

    return;

def dump_children(flag):
    it = flag.create_iterator();

    while True:
        try:
            item = next(it);
            print("Got item: {}".format(item));
        except StopIteration:
            print("Got StopIteration");
            break;

def test_flags():
    # All flags under consideration
    flags = ["a", "b", "c", "d"];

    # Root flag from which we will be searching
    root = Flag("", flags);
    it = root.create_iterator();

    dump_children(root);

    flag = lookup_flag_from_flagpath(root, ["a"]);
    dump_children(root);
    
    flag = lookup_flag_from_flagpath(root, ["c"]);
    dump_children(root);

    flag = lookup_flag_from_flagpath(root, ["c", "d"]);
    dump_children(root);

    parent = lookup_parent_flag_from_flagpath(root, ["c"]);
    dump_children(parent);

    parent = lookup_parent_flag_from_flagpath(root, ["c", "d"]);
    dump_children(parent);

def test_worker_context():
    wc = WorkerContext(0, os.path.join(os.getcwd(), 'workspace', '0'));
    wc.init_workspace();
    wc.compile([]);
    wc.size();

def main():
    work();

if __name__ == "__main__":
    main();
