# Newlib worker context

# This file is part of SimpleTuner

# Copyright (C) 2021-2023 Embecosm <www.embecosm.com>
# Contributor Maxim Blinov <maxim.blinov@embecosm.com>

# SPDX-License-Identifier: GPL-3.0-or-later

import os;
import random;
import logging;
import time;
import subprocess;

from common import CompileResult
from common import CompileRequest;
from common import get_checksum_for_filename;

class ProcessResult:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode;
        self.stdout = stdout.decode("utf-8");
        self.stderr = stderr.decode("utf-8");

class NewlibWorkerContext:
    # Return the "type" of benchmark your Worker supports.

    # This information will be used by the Simpletuner driver
    # to check the user-supplied --benchmark flag.
    @staticmethod
    def get_available_benchmark_types() -> list:
        return ["size"];

    def __init__(self, idx, workspace, cc, benchmark_type):
        # Create a logger
        self.logger = logging.getLogger("NewlibWorkerContext#{}".format(idx))

        # Absolute path to the C compiler, provided by the user via the `--cc` flag.
        self.cc = cc;

        # Our thread index
        self.idx = idx;

        # Absolute path to our workspace. We have free rein to do whatever we want here.
        self.workspace = workspace;

        # The 'type' of benchmark that will be running. This will be provided by the user via the `--benchmark` flag.
        self.benchmark_type = benchmark_type;

        random.seed(self.idx);

    # Initialise workspace, whatever that may be.
    # Simpletuner will call this function after it has created your directory and called
    # your `__init__` function. The `workspace` parameter provided earlier in
    # `__init__` is intended to be used here.
    #   Note that if you are running multi-process Simpletuner (e.g. `-j 4`), this
    # function may be running simultaneously across multiple processes.
    def init_workspace(self):
        self.logger.debug("Creating workspace in {}".format(self.workspace));

        self.march = "rv32im";
        self.mabi = "ilp32";

        if "NEWLIB_SOURCE_TAR" not in os.environ:
            self.logger.error("Please set the environment variable \"NEWLIB_SOURCE_TAR\""
                              " to contain the path to a newlib source tree.");
            return False;

        self.SOURCE_TAR = os.environ["NEWLIB_SOURCE_TAR"];

        cmd = ["tar", "-xf", self.SOURCE_TAR,
               "--directory", self.workspace];

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            self.logger.error("init_workspace(): Failed to extract:" \
                              .format(self.idx, file=sys.stderr));
            self.logger.error(stderr.decode("utf-8").strip());
            return False;

        self.newlib_source_dir = os.path.join(self.workspace);
        self.newlib_build_dir = os.path.join(self.workspace, 'build', 'newlib')

        os.makedirs(self.newlib_build_dir);

        return True;

    # Return `True` if score `x` is "better" than score `y`.
    # ----
    # Note that in this example, all the benchmark types' worst-case value is infinity.
    # But if you had for example, a `benchmark_type` that sought to maximise the No. of
    # bytes processed, or some other "bigger=better" type metric, then you would
    # put `return x > y` here.
    def better(self, x, y) -> float:
        if self.benchmark_type == "execution" or self.benchmark_type == "size":
            return x < y;


    # Return the worst possible result that is still sortable.
    # ----
    # This is used internally to deal with tests that
    # fail, and thus should be pessimized as much as possible from
    # being selected to run again.
    # The same logic applies here as in the `better(self, x, y)` function above.
    def worst_possible_result(self) -> float:
        if self.benchmark_type == "execution" or self.benchmark_type == "size":
            return float('inf');


    # Compile/clean/prepare your executable.
    # Simpletuner will call this function right before it calls your `benchmark` function.
    # ----
    # The compile step is broken out into a separate step in order to facilitate caching -
    # that is, if flag 'A' and flag 'B' both generate the exact same executable, it doesn't
    # make sense to run both, since they will both run the same way. In this case, Simpletuner
    # will skip the `benchmark` step for a flag for which it already has a cached entry.
    def newlib_clean(self, flags):
        cmd = [
            'make',
            'clean'
        ];

        res = subprocess.Popen(cmd,
                               cwd=self.newlib_build_dir,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        return ProcessResult(res.returncode, stdout, stderr)

    def newlib_configure(self, flags):
        CC = " ".join([
            'riscv32-unknown-elf-gcc',
            '-B' + os.path.join(self.newlib_build_dir, "riscv32-unknown-elf", self.march, self.mabi, "newlib"),
            '-isystem' + os.path.join(self.newlib_build_dir, "riscv32-unknown-elf", self.march, self.mabi, "newlib", "targ-include"),
            '-isystem' + os.path.join(self.newlib_source_dir, "newlib", "libc", "include"),
            '-B' + os.path.join(self.newlib_build_dir, "riscv32-unknown-elf", self.march, self.mabi, "libgloss", "riscv32"),
            '-B' + os.path.join(self.newlib_build_dir, "riscv32-unknown-elf", self.march, self.mabi, "libgloss", "libnosys"),
            '-isystem' + os.path.join(self.newlib_source_dir, "libgloss", "riscv32"),
            '-march=' + self.march,
            '-mabi=' + self.mabi
            ]);

        CFLAGS = " ".join(flags);

        cmd = [
            os.path.join(self.newlib_source_dir, 'newlib', 'configure'),
            '--with-multisubdir={}/{}'.format(self.march, self.mabi),
            '--enable-multilib',
            '--with-cross-host=x86_64-pc-linux-gnu',
            '--program-transform-name=s&^&riscv32-unknown-elf-&',
            '--disable-option-checking',
            '--with-target-subdir=riscv32-unknown-elf',
            '--build=x86_64-pc-linux-gnu',
            '--host=riscv32-unknown-elf',
            '--target=riscv32-unknown-elf',
            'CC=' + CC,
            'CFLAGS=' + CFLAGS,
        ];

        res = subprocess.Popen(cmd,
                               cwd=self.newlib_build_dir,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        return ProcessResult(res.returncode, stdout, stderr)

    def newlib_build(self, flags):
        cmd = [
            'make'
        ];

        res = subprocess.Popen(cmd,
                               cwd=self.newlib_build_dir,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        return ProcessResult(res.returncode, stdout, stderr)

    def compile(self, flags) -> CompileResult:
        self.logger.debug("[{}]: compile(): Building newlib".format(self.workspace));

        if len(os.listdir(self.newlib_build_dir)) != 0:
            configure = self.newlib_clean(flags);
            if configure.returncode != 0:
                self.logger.error("[{}]: newlib_configure(): Exit code {}: Failed to compile:" \
                                  .format(self.workspace, configure.returncode, configure.stderr));
                return CompileResult(False, None);

        configure = self.newlib_configure(flags);
        if configure.returncode != 0:
            self.logger.error("[{}]: newlib_configure(): Exit code {}: Failed to compile:" \
                              .format(self.workspace, configure.returncode, configure.stderr));
            return CompileResult(False, None);

        build = self.newlib_build(flags);
        if build.returncode != 0:
            self.logger.error("[{}]: newlib_build(): Exit code {}: Failed to compile:" \
                              .format(self.workspace, build.returncode, build.stderr));
            return CompileResult(False, None);

        # Calculate the checksum for this file. We _really_ want to do this,
        # as a lot of flags will have no effect on the binary, and this saves a lot of compute time.
        checksum = get_checksum_for_filename(os.path.join(self.newlib_build_dir, "libc.a"));

        return CompileResult(True, checksum);

    # Run whatever benchmark the user specified in `--benchmark`.
    #   Upon failure, Return `None`.
    #   Upon success, Return a floating-point arbitrary score value.
    def benchmark(self):
        if self.benchmark_type == "size":
            return self.size();
        else:
            # This should not be reachable - Make sure you sanity-check the
            # `benchmark_type` that is provided to you in the __init__ function.
            self.logger.error("Unreachable: self.benchmark_type: \"{}\" is invalid. Aborting"\
                              .format(self.benchmark_type));
            exit(1);

    def size(self):
        return self.size_find_size_of_text_section();

    def size_find_size_of_text_section(self):
        cmd = [
            "size",
            "-t",
            os.path.join(self.newlib_build_dir, "libc.a")
        ];

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            return None;

        lines = [line.strip() for line in stdout.decode("utf-8").split('\n') if len(line.strip()) > 0];

        # Get the last line: This is because 'libc.a' is actually an archive, and `size` will print the size of each object file within the archive, like so:
        # ```
        #    text    data     bss     dec     hex filename
        #     232       0       0     232      e8 lib_a-a64l.o (ex libc.a)
        #      72       0       0      72      48 lib_a-abort.o (ex libc.a)
        #      60       0       0      60      3c lib_a-abs.o (ex libc.a)
        # ...
        #     236       0       0     236      ec lib_a-xpg_strerror_r.o (ex libc.a)
        #  358917    9186    1346  369449   5a329 (TOTALS)
        # ```
        fields = [field.strip() for field in lines[-1].split()];

        text = int(fields[0]);
        data = int(fields[1]);
        bss = int(fields[2]);

        return float(text);
