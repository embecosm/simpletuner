#!/usr/bin/env python3

# Common classes

# This file is part of SimpleTuner

# Copyright (C) 2021-2023 Embecosm <www.embecosm.com>
# Contributor Maxim Blinov <maxim.blinov@embecosm.com>

# SPDX-License-Identifier: GPL-3.0-or-later

import hashlib;

class CompileRequest:
    def __init__(self):
        pass;

class CompileResult:
    def __init__(self, ok, checksum):
        self.ok = ok;
        self.checksum = checksum;

# From here: https://stackoverflow.com/a/3431835
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
