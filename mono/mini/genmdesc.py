#!/usr/bin/env python

#
# This tool is used to generate the cpu-<ARCH>.h files used by the JIT. The input is the
# cpu-<ARCH>.md file, along with the instruction metadata in mini-ops.h.
#

import sys
import os
import re

# Keep it in sync with mini.h
MONO_INST_DEST = 0
MONO_INST_SRC1 = 1
MONO_INST_SRC2 = 2
MONO_INST_SRC3 = 3
MONO_INST_LEN = 4
MONO_INST_CLOB = 5
MONO_INST_MAX = 6

allowed_defines = { "TARGET_X86" : 1,
                    "TARGET_AMD64" : 1,
                    "TARGET_ARM" : 1,
                    "TARGET_ARM64" : 1,
                    "TARGET_POWERPC" : 1,
                    "TARGET_SPARC" : 1,
                    "TARGET_S390X" : 1,
                    "TARGET_MIPS" : 1
                    }
                    
class OpDef:
    def __init__ (self, num, name, dest_def, src1_def, src2_def):
        # num is the opcode value/index
        self.num = num
        self.name = name
        self.dest_def = dest_def
        self.src1_def = src1_def
        self.src2_def = src2_def
        self.used = False
        # Data read from the cpu descriptor file
        self.spec = ["", "", "", "", "", "", "", "", "", ""]
        self.desc_idx = 0
        
def usage ():
    print ("Usage: genmdesc.py <target define> <srcdir> <output file name> <c symbol name> <input file name>")

def parse_mini_ops (target_define):
    opcodes = {}
    opcode_id = 0
    enabled = [target_define]
    is_enabled = True
    opcode_file = open (os.path.join (srcdir, "mini-ops.h"))
    #
    # Implement a subset of a c preprocessor, only handling #ifdef/#endif directives
    #
    for line in opcode_file:
        line = line.strip ()
        # print ("{0} {1}".format (line, is_enabled))
        m = re.search (r'^\s*#if (.+)', line)
        # FIXME: Check list of defines against an allowed list
        if m != None:
            is_enabled = False
            parts = m.group (1).split ("||")
            for part in parts:
                part = part.strip ()
                m = re.search (r'defined\((.+)\)', part)
                if m == None:
                    print ("Unknown #ifdef line {0}".format (line))
                    exit (1)
                define = m.group (1)
                # Check that the file only contains TARGET_... defines
                if not define in allowed_defines:
                    print ("Unknown define '{0}' in mini-ops.h".format (define))
                    exit (1)
                for d in enabled:
                    if d == define:
                        is_enabled = True
        elif line == "#endif":
            is_enabled = True
        else:
            if is_enabled and line.startswith ("MINI_OP"):
                m = re.search (r"MINI_OP\(\w+\s*\,\s*\"([^\"]+)\", (\w+), (\w+), (\w+)\)", line)
                if m != None:
                    opcodes [m.group (1)] = OpDef(opcode_id, m.group (1), m.group (2), m.group (3), m.group (4))
                else:
                    m = re.search (r"MINI_OP3\(\w+\s*\,\s*\"([^\"]+)\", (\w+), (\w+), (\w+), (\w+)\)", line)
                    if m != None:
                        opcodes [m.group (1)] = OpDef(opcode_id, m.group (1), m.group (2), m.group (3), m.group (4))
                    else:
                        print ("Unable to parse line: '{0}'".format (line))
                        exit (1)
                opcode_id += 1
    opcode_file.close ()
    return opcodes

def parse_input(infile, opcodes):
    for line in infile:
        line = line.strip ()
        if line == "" or line.startswith ("#"):
            continue
        # Lines look like:
        # expand_i2: dest:x src1:i len:18
        parts = line.split (" ")
        op_name = parts [0][:-1]
        if not op_name in opcodes:
            print ("Unknown opcode '{0}'".format (op_name))
            exit (1)
        opcode = opcodes [op_name]
        opcode.used = True
        for part in parts[1:]:
            part = part.strip ()
            if part == "":
                continue
            [spec, value] = part.split (":")
            if spec == "dest":
                if opcode.dest_def == "NONE":
                    print ("Inconsistent dreg for opcode '{0}'".format (op_name))
                opcode.spec [MONO_INST_DEST] = value
            elif spec == "src1":
                if opcode.src1_def == "NONE":
                    print ("Inconsistent src1 for opcode '{0}'".format (op_name))
                opcode.spec [MONO_INST_SRC1] = value
            elif spec == "src2":
                if opcode.src2_def == "NONE":
                    print ("Inconsistent src2 for opcode '{0}'".format (op_name))
                opcode.spec [MONO_INST_SRC2] = value
            elif spec == "src3":
                opcode.spec [MONO_INST_SRC3] = value
            elif spec == "len":
                opcode.spec [MONO_INST_LEN] = chr(int(value))
            elif spec == "clob":
                opcode.spec [MONO_INST_CLOB] = value
            else:
                print ("Unknown specifier '{0}' for opcode '{0}'".format (spec))
                exit (1)

def gen_output(f, opcodes):
    sorted_opcodes = []
    for op in opcodes.values ():
        sorted_opcodes.append (op)
    sorted_opcodes.sort (key=lambda op: op.num)

    f.write ("/* File automatically generated by genmdesc.py, don't change */\n\n")

    # Write desc table
    f.write ("const char mono_{0} [] = {{\n".format (symbol_name))
    f.write ("\t\"")
    for i in range(MONO_INST_MAX):
        f.write (r"\x0")
    f.write ("\"\t/* null entry */\n")
    idx = 1
    for op in sorted_opcodes:
        if not op.used:
            continue
        try:
            f.write ("\t\"")
            for c in op.spec[:MONO_INST_MAX]:
                if c == "":
                    f.write (r"\x0")
                    f.write ("\" \"")
                elif c.isalnum ():
                    f.write (c)
                else:
                    f.write (r"\x{0:x}".format (ord (c)))
                    f.write ("\" \"")
            f.write ("\"\t/* {0} */\n".format (op.name))
            op.desc_idx = idx * MONO_INST_MAX
            idx += 1
        except:
            print ("Error emitting opcode '{0}': '{1}'.".format (op.name, sys.exc_info()))
    f.write ("};\n")

    # Write index table
    f.write ("const guint16 mono_{0}_idx [] = {{\n".format (symbol_name))
    for op in sorted_opcodes:
        if not op.used:
            f.write ("\t0,\t/* {0} */\n".format (op.name))
        else:
            f.write ("\t{0},\t/* {1} */\n".format (op.desc_idx, op.name))
    f.write ("};\n\n")

#
# MAIN
#

if len (sys.argv) != 6:
    usage ()
    exit (1)

target_define = sys.argv [1]
srcdir = sys.argv [2]
outfile_name = sys.argv [3]
symbol_name = sys.argv [4]
infile_name = sys.argv [5]

# Parse mini-ops.h file for opcode metadata
opcodes = parse_mini_ops(target_define)

# Parse input file
infile = open (infile_name, 'r')
parse_input (infile, opcodes)

# Generate output
f = open (outfile_name, 'w')
gen_output (f, opcodes)
f.close ()
