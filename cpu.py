"""The CPU.

The CPU in the original GameBoy is a modified Zilog Z80.

http://www.devrs.com/gb/files/opcodes.html :
The GameBoy has instructions & registers similiar to the 8080, 8085, & Z80
microprocessors. The internal 8-bit registers are A, B, C, D, E, F, H, & L.
These registers may be used in pairs for 16-bit operations as AF, BC, DE, &
HL. The two remaining 16-bit registers are the program counter (PC) and the
stack pointer (SP).

The F register holds the cpu flags. The operation of these flags is identical
to their Z80 relative. The lower four bits of this register always read zero
even if written with a one.

Flag Register
7   6   5   4   3   2   1   0
Z   N   H   C   0   0   0   0
The GameBoy CPU is based on a subset of the Z80 microprocessor.
A summary of these commands is given below.

Mnemonic    Symbolic Operation  Comments    CPU Clocks  Flags - Z,N,H,C
8-Bit Loads
-----------
LD r,s  r   s   s=r,n,(HL)  r=4, n=8, (HL)=8
LD d,r  d   r   d=r,(HL)    r=4, (HL)=8
LD d,n  d   n   r=8, (HL)=12
LD A,(ss)   A   (ss)    ss=BC,DE,HL,nn  [BC,DE,HL]=8, nn=16
LD (dd),A   (dd)   A    dd=BC,DE,HL,nn
LD A,(C)    A   ($FF00+C)   -   8
LD (C),A    ($FF00+C)   A   8
LDD A,(HL)  A   (HL), HL   HL - 1   8
LDD (HL),A  (HL)   A, HL   HL - 1   8
LDI A,(HL)  A   (HL), HL   HL + 1   8
LDI (HL),A  (HL)   A, HL   HL + 1   8
LDH (n),A   ($FF00+n)   A   12
LDH A,(n)   A   ($FF00+n)   12

16-Bit Loads
------------
LD dd,nn    dd   nn dd=BC,DE,HL,SP  12  -   -   -   -
LD (nn),SP  (nn)   SP   -   20
LD SP,HL    SP   HL 8
LD HL,(SP+e)    HL   (SP+e) 12  0   0   *   *
PUSH ss (SP-1)  ssh, (SP-2)  ssl, SPSP-2    ss=BC,DE,HL,AF  16  -   -   -   -
POP dd  ddl   (SP), ddh   (SP+1), SPSP+2    dd=BC,DE,HL,AF  12

8-Bit ALU
---------
ADD A,s A   A + s   CY is the carry flag. s=r,n,(HL)    r=4, n=8, (HL)=8    *   0   *   *
ADC A,s A   A + s + CY
SUB s   A   A - s   *   1   *   *
SBC A,s A   A - s - CY
AND s   A   A   s   *   0   1   0
OR s    A   A   s   *   0   0   0
XOR s   A   A   s
CP s    A - s   *   1   *   *
INC s   s   s + 1   s=r,(HL)    r=4, (HL)=12    *   0   *   -
DEC s   s   s - 1   *   1   *   -

16-Bit Arithmetic
-----------------
ADD HL,ss   HL   HL + ss    ss=BC,DE,HL,SP  8   -   0   *   *
ADD SP,e    SP   SP + e 16  0   0   *   *
INC ss  ss   ss + 1 8   -   -   -   -
DEC ss  ss   ss - 1 8

Miscellaneous
-------------
SWAP s      Swap nibbles. s=r,(HL)  r=8, (HL)=16    *   0   0   0
DAA Converts A into packed BCD. -   4   *   -   0   *
CPL A   /A  4   -   1   1   -
CCF CY  /CY CY is the carry flag.   4   -   0   0   *
SCF CY   1  4   -   0   0   1
NOP No operation.   -   4   -   -   -   -
HALT    Halt CPU until an interrupt occurs. 4
STOP    Halt CPU.   4
DI  Disable Interrupts. 4
EI  Enable Interrupts.  4

Rotates & Shifts
----------------
RLCA            4   0   0   0   *
RLA
RRCA
RRA
RLC s       s=A,r,(HL)  r=8,(HL)=16 *   0   0   *
RL s
RRC s
RR s
SLA s       s=r,(HL)    r=8, (HL)=16
SRA s
SRL s

Bit Opcodes
-----------
BIT b,s Z   /sb Z is zero flag. s=r,(HL)    r=8, (HL)=12    *   0   1   -
SET b,s sb   1  r=8, (HL)=16    -   -   -   -
RES b,s sb   0

Jumps
-----
JP nn   PC   nn -   16
JP cc,nn    If cc is true, PC   nn, else continue.  If cc is true, 16 else 12.
JP (HL) PC   HL 4
JR e    PC   PC + e 12
JR cc,e if cc is true, PC   PC + e, else continue.  If cc is true, 12 else 8.

Calls
-----
CALL nn (SP-1)   PCh, (SP-2)  PCl, PC  nn, SPSP-2   -   24
CALL cc,nn  If condition cc is false continue, else same as CALL nn.    If cc is true, 24 else 12.

Restarts
--------
RST f   (SP-1)   PCh, (SP-2)  PCl, PCh  0, PCl  f, SPSP-2   -   16

Returns
-------
RET pcl   (SP), pch   (SP+1), SPSP+2    -   16
RET cc  If cc is true, RET else continue.   If cc is true, 20 else 8.
RETI    Return then enable interrupts.  16
"""

# import pdb

FLAG = {
    'zero': 0x80,           # Z flag
    'sub': 0x40,    # N flag
    'half-carry': 0x20,     # H flag
    'carry': 0x10           # C flag
}
FLAG_ZERO = 0x80
FLAG_HALF_CARRY = 0x20
FLAG_CARRY = 0x10
CB_REGISTER_NAMES = ('b', 'c', 'd', 'e', 'h', 'l', None, 'a')
PPU_MODE_CYCLES = (204, 456, 80, 172)
OP_FAST_LY_COMPARE_B_LOOP = 0x100
OP_FAST_CP_HL_JR_NZ_LOOP = 0x101
OP_FAST_STAT_MODE_POLL_LOOP = 0x102
OP_FAST_LY_ZERO_LOOP = 0x103
OP_FAST_ROM_BIT_DECODE_OUTPUT_LOOP = 0x104
OP_FAST_ROM_BIT_READER_HELPER = 0x105
PSEUDO_OPCODE_BASE = 0x100
OP_FAST_HRAM_POLL_LOOP_BASE = 0x200
INLINE_OPCODE_MASK = bytearray(256)
for _op in (0x05, 0x12, 0x20, 0x21, 0x22, 0x23, 0x28, 0x2A,
            0x3D, 0xA7, 0xB8, 0xBE, 0xCB, 0xF0):
    INLINE_OPCODE_MASK[_op] = 1
my_counter = 0


def _build_cp_flag_table():
    """Return flags for CP A,value indexed by ``(A << 8) | value``."""
    table = bytearray(0x10000)
    for a in range(0x100):
        base = a << 8
        for value in range(0x100):
            result = a - value
            flags = FLAG['sub']
            if result == 0:
                flags |= FLAG_ZERO
            if (a & 0x0F) < (value & 0x0F):
                flags |= FLAG_HALF_CARRY
            if result < 0:
                flags |= FLAG_CARRY
            table[base | value] = flags
    return table


CP_FLAG_TABLE = _build_cp_flag_table()


class ExecutionHalted(Exception):
    """Raised when execution should stop."""
    pass


class GbZ80Cpu(object):
    """The Z80 CPU class."""

    def __init__(self, log_dump, gb_doctor_test_mode, trace_enabled=False):
        """Initialize an instance."""
        self.gb_doctor_test_mode = gb_doctor_test_mode
        self.trace_enabled = trace_enabled
        self.enable_interrupts_next_cycle = False
        self.halted = False
        self.clock = {'m': 0}  # Time clock
        self.log_dump = log_dump
        self.sys_interface = None    # Set after interface instantiated.
        self.direct_rom = None
        self.decoded_rom_ops = None
        self.decoded_rom_ops_length = 0
        self.direct_rom_length = 0
        self.hram_poll_loop_ldh_offsets = {}
        self.hram_compare_b_loop_ldh_offsets = {}
        self.cp_hl_jr_nz_loop_pcs = set()
        self.opcode_counts = None
        self.cb_opcode_counts = None
        self.slow_diagnostics_enabled = False
        self.slow_opcode_counts = [0] * 0x300
        self.slow_cb_opcode_counts = [0] * 256
        self.slow_pc_counts = {}
        self.slow_instruction_count = 0
        self.diagnostics_enabled = False
        self.diagnostics = {}
        self.pc_sample_start = None
        self.pc_sample_end = None
        self.pc_sample_limit = 20
        self.halt_m_cycles = 0

        # Register set
        self.registers = {
            # 16-bit registers stored as two 8-bit registers
            'a': 0x01, 'f': 0xB0,
            'b': 0x00, 'c': 0x13,
            'd': 0x00, 'e': 0xD8,
            'h': 0x01, 'l': 0x4D,

            # Interrupts enabled/disabled
            'ime': 1,

            # 16-bit registers (program counter, stack pointer)
            'pc': 0x0100, 'sp': 0xFFFE,

            # Clock for last instr
            'm': 0      # cpu cycles/4
        }

        self.rsv = {'a': 0, 'b': 0, 'c': 0, 'd': 0, 'e': 0, 'f': 0,
                    'h': 0, 'l': 0}

        self.opcode_map = {
            # opcode number: func to call, args
            0: (self._nop, ()),  # NOP
            1: (self._ld_r1r2_nn, ('b', 'c')),  # LDBCnn
            2: (self._ld_r1r2m_a, ('b', 'c')),  # LDBCmA
            3: (self._inc_r_r, ('b', 'c')),  # INCBC
            4: (self._inc_r, ('b',)),  # INCr_b
            5: (self._dec_r, ('b',)),  # DECr_b
            6: (self._ld_rn, ('b',)),  # LDrn_b
            7: (self._rlc_a, ()),  # RLCA
            8: (self._ld_nn_sp, ()),  # LDnnSP
            9: (self._add_hl_n, ('b', 'c')),  # ADDHLBC
            10: (self._ld_a_r1r2m, ('b', 'c')),  # LDABCm
            11: (self._dec_bc, ()),  # DECBC
            12: (self._inc_r, ('c',)),  # INCr_c
            13: (self._dec_r, ('c',)),  # DECr_c
            14: (self._ld_rn, ('c',)),  # LDrn_c
            15: (self._rrca, ()),  # RRCA
            # 16: (self._djnz_n, ()),  # DJNZn or stop?
            16: (self._stop, ()),  # DJNZn or stop?
            17: (self._ld_r1r2_nn, ('d', 'e')),  # LDDEnn
            18: (self._ld_de_a, ()),  # LDDEmA
            19: (self._inc_r_r, ('d', 'e')),  # INCDE
            20: (self._inc_r, ('d',)),  # INCr_d
            21: (self._dec_r, ('d',)),  # DECr_d
            22: (self._ld_rn, ('d',)),  # LDrn_d
            23: (self._rla, ()),  # RLA
            24: (self._jr_n, ()),  # JRn
            25: (self._add_hl_n, ('d', 'e')),  # ADDHLDE
            26: (self._ld_a_r1r2m, ('d', 'e')),  # LDADEm
            27: (self._dec_r_r, ('d', 'e')),  # DECDE
            28: (self._inc_r, ('e',)),  # INCr_e
            29: (self._dec_r, ('e',)),  # DECr_e
            30: (self._ld_rn, ('e',)),  # LDrn_e
            31: (self._rra, ()),  # RRA
            32: (self._jr_nz_n, ()),  # JRNZn
            33: (self._ld_hl_nn, ()),  # LDHLnn
            34: (self._ld_hlmi_a, ()),  # LDHLIA
            35: (self._inc_hl, ()),  # INCHL
            36: (self._inc_r, ('h',)),  # INCr_h
            37: (self._dec_r, ('h',)),  # DECr_h
            38: (self._ld_rn, ('h',)),  # LDrn_h
            39: (self._daa, ()),  # DAA
            40: (self._jr_z_n, ()),  # JRZn
            41: (self._add_hl_n, ('h', 'l')),  # ADDHLHL
            42: (self._ld_a_hl_i, ()),  # LDAHLI
            43: (self._dec_r_r, ('h', 'l')),  # DECHL
            44: (self._inc_r, ('l',)),  # INCr_l
            45: (self._dec_r, ('l',)),  # DECr_l
            46: (self._ld_rn, ('l',)),  # LDrn_l
            47: (self.cpl, ()),  # CPL
            48: (self._jr_cc_n, (0x10, 0x00)),  # JRNCn
            49: (self._ld_sp_nn, ()),  # LD SP nn
            50: (self._ld_hlmd_a, ()),  # LDHLDA
            51: (self._inc_sp, ()),  # INC SP
            52: (self._inc_hlm, ()),  # INCHLm
            53: (self._dec_hlm, ()),  # DECHLm
            54: (self._ld_hlm_n, ()),  # LDHLmn
            55: (self._scf, ()),  # SCF
            56: (self._jr_cc_n, (0x10, 0x10)),  # JRCn
            57: (self._add_hl_sp, ()),  # ADDHLSP
            58: (self._ld_a_hl_d, ()),  # LDAHLD
            59: (self._dec_sp, ()),  # DECSP
            60: (self._inc_r, ('a',)),  # INCr_a
            61: (self._dec_a, ()),  # DECr_a
            62: (self._ld_rn, ('a',)),  # LDrn_a
            63: (self._ccf, ()),  # CCF
            64: (self._ld_rr, ('b', 'b')),  # LDrr_bb (nop?)
            65: (self._ld_rr, ('b', 'c')),  # LDrr_bc
            66: (self._ld_rr, ('b', 'd')),  # LDrr_bd
            67: (self._ld_rr, ('b', 'e')),  # LDrr_be
            68: (self._ld_rr, ('b', 'h')),  # LDrr_bh
            69: (self._ld_rr, ('b', 'l')),  # LDrr_bl
            70: (self._ld_r_hlm, ('b',)),  # LDrHLm_b
            71: (self._ld_rr, ('b', 'a')),  # LDrr_ba
            72: (self._ld_rr, ('c', 'b')),  # LDrr_cb
            73: (self._ld_rr, ('c', 'c')),  # LDrr_cc (nop?)
            74: (self._ld_rr, ('c', 'd')),  # LDrr_cd
            75: (self._ld_rr, ('c', 'e')),  # LDrr_ce
            76: (self._ld_rr, ('c', 'h')),  # LDrr_ch
            77: (self._ld_rr, ('c', 'l')),  # LDrr_cl
            78: (self._ld_r_hlm, ('c',)),  # LDrHLm_c
            79: (self._ld_rr, ('c', 'a')),  # LDrr_ca
            80: (self._ld_rr, ('d', 'b')),  # LDrr_db
            81: (self._ld_rr, ('d', 'c')),  # LDrr_dc
            82: (self._ld_rr, ('d', 'd')),  # LDrr_dd (nop?)
            83: (self._ld_rr, ('d', 'e')),  # LDrr_de
            84: (self._ld_rr, ('d', 'h')),  # LDrr_dh
            85: (self._ld_rr, ('d', 'l')),  # LDrr_dl
            86: (self._ld_r_hlm, ('d',)),  # LDrHLm_d
            87: (self._ld_rr, ('d', 'a')),  # LDrr_da
            88: (self._ld_rr, ('e', 'b')),  # LDrr_eb
            89: (self._ld_rr, ('e', 'c')),  # LDrr_ec
            90: (self._ld_rr, ('e', 'd')),  # LDrr_ed
            91: (self._ld_rr, ('e', 'e')),  # LDrr_ee (nop?)
            92: (self._ld_rr, ('e', 'h')),  # LDrr_eh
            93: (self._ld_rr, ('e', 'l')),  # LDrr_el
            94: (self._ld_r_hlm, ('e',)),  # LDrHLm_e
            95: (self._ld_rr, ('e', 'a')),  # LDrr_ea
            96: (self._ld_rr, ('h', 'b')),  # LDrr_hb
            97: (self._ld_rr, ('h', 'c')),  # LDrr_hc
            98: (self._ld_rr, ('h', 'd')),  # LDrr_hd
            99: (self._ld_rr, ('h', 'e')),  # LDrr_he
            100: (self._ld_rr, ('h', 'h')),  # LDrr_hh (nop?)
            101: (self._ld_rr, ('h', 'l')),  # LDrr_hl
            102: (self._ld_r_hlm, ('h',)),  # LDrHLm_h
            103: (self._ld_rr, ('h', 'a')),  # LDrr_ha
            104: (self._ld_rr, ('l', 'b')),  # LDrr_lb
            105: (self._ld_rr, ('l', 'c')),  # LDrr_lc
            106: (self._ld_rr, ('l', 'd')),  # LDrr_ld
            107: (self._ld_rr, ('l', 'e')),  # LDrr_le
            108: (self._ld_rr, ('l', 'h')),  # LDrr_lh
            109: (self._ld_rr, ('l', 'l')),  # LDrr_ll (nop?)
            110: (self._ld_r_hlm, ('l',)),  # LDrHLm_l
            111: (self._ld_rr, ('l', 'a')),  # LDrr_la
            112: (self._ld_hlm_r, ('b',)),  # LDHLmr_b
            113: (self._ld_hlm_r, ('c',)),  # LDHLmr_c
            114: (self._ld_hlm_r, ('d',)),  # LDHLmr_d
            115: (self._ld_hlm_r, ('e',)),  # LDHLmr_e
            116: (self._ld_hlm_r, ('h',)),  # LDHLmr_h
            117: (self._ld_hlm_r, ('l',)),  # LDHLmr_l
            118: (self._halt, ()),  # HALT
            119: (self._ld_hlm_r, ('a',)),  # LDHLmr_a
            120: (self._ld_a_b, ()),  # LDrr_ab
            121: (self._ld_rr, ('a', 'c')),  # LDrr_ac
            122: (self._ld_rr, ('a', 'd')),  # LDrr_ad
            123: (self._ld_rr, ('a', 'e')),  # LDrr_ae
            124: (self._ld_rr, ('a', 'h')),  # LDrr_ah
            125: (self._ld_a_l, ()),  # LDrr_al
            126: (self._ld_a_hlm, ()),  # LDrHLm_a
            127: (self._ld_rr, ('a', 'a')),  # LDrr_aa (nop?)
            128: (self._add_a_n, ('b',)),  # ADDr_b
            129: (self._add_a_n, ('c',)),  # ADDr_c
            130: (self._add_a_n, ('d',)),  # ADDr_d
            131: (self._add_a_n, ('e',)),  # ADDr_e
            132: (self._add_a_n, ('h',)),  # ADDr_h
            133: (self._add_a_n, ('l',)),  # ADDr_l
            134: (self._add_a_hl, ()),  # ADD A,(HL)
            135: (self._add_a_n, ('a',)),  # ADDr_a
            136: (self._adc_a_n, ('b',)),  # ADC A, B
            137: (self._adc_a_n, ('c',)),  # ADC A, C
            138: (self._adc_a_n, ('d',)),  # ADC A, D
            139: (self._adc_a_n, ('e',)),  # ADC A, E
            140: (self._adc_a_n, ('h',)),  # ADC A, H
            141: (self._adc_a_n, ('l',)),  # ADC A, L
            142: (self._adc_hl, ()),  # ADCHL
            143: (self._adc_a_n, ('a',)),  # ADCr_a
            144: (self._sub_n, ('b',)),  # SUBr_b
            145: (self._sub_n, ('c',)),  # SUBr_c
            146: (self._sub_n, ('d',)),  # SUBr_d
            147: (self._sub_n, ('e',)),  # SUBr_e
            148: (self._sub_n, ('h',)),  # SUBr_h
            149: (self._sub_n, ('l',)),  # SUBr_l
            150: (self._sub_hl, ()),  # SUBHL
            151: (self._sub_n, ('a',)),  # SUBr_a
            152: (self._sub_a_n, ('b',)),  # SBCr_b
            153: (self._sub_a_n, ('c',)),  # SBCr_c
            154: (self._sub_a_n, ('d',)),  # SBCr_d
            155: (self._sub_a_n, ('e',)),  # SBCr_e
            156: (self._sub_a_n, ('h',)),  # SBCr_h
            157: (self._sub_a_n, ('l',)),  # SBCr_l
            158: (self._sbc_a_hl, ()),  # SBC A,(HL)
            159: (self._sub_a_n, ('a',)),  # SBCr_a
            160: (self._and_b, ()),  # ANDr_b
            161: (self._and_n, ('c',)),  # ANDr_c
            162: (self._and_n, ('d',)),  # ANDr_d
            163: (self._and_n, ('e',)),  # ANDr_e
            164: (self._and_n, ('h',)),  # ANDr_h
            165: (self._and_n, ('l',)),  # ANDr_l
            166: (self._and_n, ('hl',)),  # ANDHL
            167: (self._and_a, ()),  # ANDr_a
            168: (self._xor_a_n, ('b',)),  # XORr_b
            169: (self._xor_a_n, ('c',)),  # XORr_c
            170: (self._xor_a_n, ('d',)),  # XORr_d
            171: (self._xor_a_n, ('e',)),  # XORr_e
            172: (self._xor_a_n, ('h',)),  # XORr_h
            173: (self._xor_a_n, ('l',)),  # XORr_l
            174: (self._xor_hl, ()),  # XORHL
            175: (self._xor_a_n, ('a',)),  # XORr_a
            176: (self._or_n, ('b',)),  # ORr_b
            177: (self._or_c, ()),  # ORr_c
            178: (self._or_n, ('d',)),  # ORr_d
            179: (self._or_n, ('e',)),  # ORr_e
            180: (self._or_n, ('h',)),  # ORr_h
            181: (self._or_n, ('l',)),  # ORr_l
            182: (self._or_hl, ()),  # ORHL
            183: (self._or_n, ('a',)),  # ORr_a
            184: (self._cp_b, ()),  # CPr_b
            185: (self._cp_n, ('c',)),  # CPr_c
            186: (self._cp_n, ('d',)),  # CPr_d
            187: (self._cp_n, ('e',)),  # CPr_e
            188: (self._cp_n, ('h',)),  # CPr_h
            189: (self._cp_n, ('l',)),  # CPr_l
            190: (self._cp_hl, ()),  # CP (HL)
            191: (self._cp_n, ('a',)),  # CPr_a
            192: (self._ret_f, (FLAG['zero'], 0x00)),  # RETNZ
            193: (self._pop_nn, ('b', 'c')),  # POPBC
            194: (self._jp_cc_nn, (FLAG['zero'], 0x00)),  # JPNZnn
            195: (self._jp_nn, ()),  # JPnn
            196: (self._call_cc_nn, (FLAG['zero'], 0x00)),  # CALL NZ,nn
            197: (self._push_nn, ('b', 'c')),  # PUSHBC
            198: (self._add_n, ()),  # ADDn
            199: (self._rst_n, (0x00,)),  # RST00
            200: (self._ret_f, (FLAG['zero'], FLAG['zero'])),  # RETZ
            201: (self._ret, ()),  # RET
            202: (self._jp_cc_nn, (FLAG['zero'], FLAG['zero'])),  # JPZnn
            203: (self._call_cb_op, ()),  # MAPcb
            204: (self._call_cc_nn, (FLAG['zero'], FLAG['zero'])),  # CALL Z,nn
            205: (self._call_nn, ()),  # CALLnn
            206: (self._adc_n, ()),  # ADCn
            207: (self._rst_n, (0x08,)),  # RST08
            208: (self._ret_f, (FLAG['carry'], 0x00)),  # RETNC
            209: (self._pop_nn, ('d', 'e')),  # POPDE
            210: (self._jp_cc_nn, (FLAG['carry'], 0x00)),  # JPNCnn
            211: (self._nop, ()),  # XX
            212: (self._call_cc_nn, (FLAG['carry'], 0x00)), # CALL NC,nn
            213: (self._push_nn, ('d', 'e')),  # PUSHDE
            214: (self._sub_n_imm, ()),  # SUBn
            215: (self._rst_n, (FLAG['carry'],)),  # RST10
            216: (self._ret_f, (FLAG['carry'], FLAG['carry'])),  # RETC
            217: (self._reti, ()),  # RETI
            218: (self._jp_cc_nn, (FLAG['carry'], FLAG['carry'])),  # JPCnn
            219: (self._nop, ()),  # XX
            220: (self._call_cc_nn, (FLAG['carry'], FLAG['carry'])), # CALL C,nn
            221: (self._nop, ()),  # XX
            222: (self._sbc_n, ()),  # SBC A,n
            223: (self._rst_n, (0x18,)),  # RST18
            224: (self._ldh_n_a, ()),  # LDIOnA
            225: (self._pop_nn, ('h', 'l')),  # POPHL
            226: (self._ld_c_a, ()),  # LDIOCA
            227: (self._nop, ()),  # XX
            228: (self._nop, ()),  # XX
            229: (self._push_nn, ('h', 'l')),  # PUSHHL
            230: (self._and_pc, ()),  # ANDn
            231: (self._rst_n, (FLAG['half-carry'],)),  # RST20
            232: (self._add_sp_n, ()),  # ADDSPn
            233: (self._jp_hl, ()),  # JPHL
            234: (self._ld_nn_a, ()),  # LD nn A
            235: (self._nop, ()),  # XX
            236: (self._nop, ()),  # XX
            237: (self._nop, ()),  # XX
            238: (self._xor_n_imm, ()),  # ORn
            239: (self._rst_n, (0x28,)),  # RST28
            240: (self._ldh_a_n, ()),  # LD AIO n
            241: (self._pop_nn, ('a', 'f')),  # POPAF
            242: (self._ld_a_c, ()),  # LDAIOC
            243: (self._di, ()),  # DI
            244: (self._nop, ()),  # XX
            245: (self._push_nn, ('a', 'f')),  # PUSHAF
            246: (self._or_n_imm, ()),  # ORn
            247: (self._rst_n, (0x30,)),  # RST30
            248: (self._ld_hl_sp_n, ()),  # LD HL SP+n
            249: (self._ld_sp_hl, ()),  # LS SP HL
            250: (self._ld_a_nn, ()),  # LD A nn
            251: (self._ei, ()),  # EI
            252: (self._nop, ()),  # XX
            253: (self._nop, ()),  # XX
            254: (self._cp_n, ('pc',)),  # CPn
            255: (self._rst_n, (0x38,)),  # RST38
        }

        self.cb_map = {
            0: (self._rlc_n, ['b']),  # RLCr_b
            1: (self._rlc_n, ['c']),  # RLCr_c
            2: (self._rlc_n, ['d']),  # RLCr_d
            3: (self._rlc_n, ['e']),  # RLCr_e
            4: (self._rlc_n, ['h']),  # RLCr_h
            5: (self._rlc_n, ['l']),  # RLCr_l
            6: (self._rlc_hlm, ()),  # RLC (HL)
            7: (self._rlc_n, ['a']),  # RLCr_a
            8: (self._rrc_n, ['b']),  # RRC B
            9: (self._rrc_n, ['c']),  # RRC C
            10: (self._rrc_n, ['d']),  # RRC D
            11: (self._rrc_n, ['e']),  # RRC E
            12: (self._rrc_n, ['h']),  # RRC H
            13: (self._rrc_n, ['l']),  # RRC L
            14: (self._rrc_hlm, ()),  # RRC (HL)
            15: (self._rrc_n, ['a']),  # RRC A
            16: (self._rl_n, ['b']),  # RL B
            17: (self._rl_n, ['c']),  # RL C
            18: (self._rl_n, ['d']),  # RL D
            19: (self._rl_n, ['e']),  # RL E
            20: (self._rl_n, ['h']),  # RL H
            21: (self._rl_n, ['l']),  # RL L
            22: (self._rl_hlm, ()),  # RL (HL)
            23: (self._rl_n, ['a']),  # RL A
            24: (self._rr_n, ['b']),  # RR B
            25: (self._rr_n, ['c']),  # RR C
            26: (self._rr_n, ['d']),  # RR D
            27: (self._rr_n, ['e']),  # RR E
            28: (self._rr_n, ['h']),  # RR H
            29: (self._rr_n, ['l']),  # RR L
            30: (self._rr_hlm, ()),  # RR (HL)
            31: (self._rr_n, ['a']),  # RR A
            32: (self._sla_n, ['b']),  # SLA B
            33: (self._sla_n, ['c']),  # SLA C
            34: (self._sla_n, ['d']),  # SLA D
            35: (self._sla_n, ['e']),  # SLA E
            36: (self._sla_n, ['h']),  # SLA H
            37: (self._sla_n, ['l']),  # SLA L
            38: (self._sla_hlm, ()),  # SLA (HL)
            39: (self._sla_n, ['a']),  # SLA A
            40: (self._sra_n, ['b']),  # SRA B
            41: (self._sra_n, ['c']),  # SRA C
            42: (self._sra_n, ['d']),  # SRA D
            43: (self._sra_n, ['e']),  # SRA E
            44: (self._sra_n, ['h']),  # SRA H
            45: (self._sra_n, ['l']),  # SRA L
            46: (self._sra_hlm, ()),  # SRA (HL)
            47: (self._sra_n, ['a']),  # SRA A
            48: (self._swap_n, ['b']),  # SWAPr_b
            49: (self._swap_n, ['c']),  # SWAPr_c
            50: (self._swap_n, ['d']),  # SWAPr_d
            51: (self._swap_n, ['e']),  # SWAPr_e
            52: (self._swap_n, ['h']),  # SWAPr_h
            53: (self._swap_n, ['l']),  # SWAPr_l
            54: (self._swap_hlm, ()),  # SWAP (HL)
            55: (self._swap_n, ['a']),  # SWAPr_a
            56: (self._srl_n, ['b']),  # SRL B
            57: (self._srl_n, ['c']),  # SRL C
            58: (self._srl_n, ['d']),  # SRL D
            59: (self._srl_n, ['e']),  # SRL E
            60: (self._srl_n, ['h']),  # SRL H
            61: (self._srl_n, ['l']),  # SRL L
            62: (self._srl_hlm, ()),  # SRL (HL)
            63: (self._srl_n, ['a']),  # SRL A
            # BIT 0
            64: (self._bit_test_r, [0, 'b']),
            65: (self._bit_test_r, [0, 'c']),
            66: (self._bit_test_r, [0, 'd']),
            67: (self._bit_test_r, [0, 'e']),
            68: (self._bit_test_r, [0, 'h']),
            69: (self._bit_test_r, [0, 'l']),
            70: (self._bit_test_hlm, [0]),
            71: (self._bit_test_r, [0, 'a']),
            # BIT 1
            72: (self._bit_test_r, [1, 'b']),
            73: (self._bit_test_r, [1, 'c']),
            74: (self._bit_test_r, [1, 'd']),
            75: (self._bit_test_r, [1, 'e']),
            76: (self._bit_test_r, [1, 'h']),
            77: (self._bit_test_r, [1, 'l']),
            78: (self._bit_test_hlm, [1]),
            79: (self._bit_test_r, [1, 'a']),
            # BIT 2
            80: (self._bit_test_r, [2, 'b']),
            81: (self._bit_test_r, [2, 'c']),
            82: (self._bit_test_r, [2, 'd']),
            83: (self._bit_test_r, [2, 'e']),
            84: (self._bit_test_r, [2, 'h']),
            85: (self._bit_test_r, [2, 'l']),
            86: (self._bit_test_hlm, [2]),
            87: (self._bit_test_r, [2, 'a']),
            # BIT 3
            88: (self._bit_test_r, [3, 'b']),
            89: (self._bit_test_r, [3, 'c']),
            90: (self._bit_test_r, [3, 'd']),
            91: (self._bit_test_r, [3, 'e']),
            92: (self._bit_test_r, [3, 'h']),
            93: (self._bit_test_r, [3, 'l']),
            94: (self._bit_test_hlm, [3]),
            95: (self._bit_test_r, [3, 'a']),
            # BIT 4
            96: (self._bit_test_r, [4, 'b']),
            97: (self._bit_test_r, [4, 'c']),
            98: (self._bit_test_r, [4, 'd']),
            99: (self._bit_test_r, [4, 'e']),
            100: (self._bit_test_r, [4, 'h']),
            101: (self._bit_test_r, [4, 'l']),
            102: (self._bit_test_hlm, [4]),
            103: (self._bit_test_r, [4, 'a']),
            # BIT 5
            104: (self._bit_test_r, [5, 'b']),
            105: (self._bit_test_r, [5, 'c']),
            106: (self._bit_test_r, [5, 'd']),
            107: (self._bit_test_r, [5, 'e']),
            108: (self._bit_test_r, [5, 'h']),
            109: (self._bit_test_r, [5, 'l']),
            110: (self._bit_test_hlm, [5]),
            111: (self._bit_test_r, [5, 'a']),
            # BIT 6
            112: (self._bit_test_r, [6, 'b']),
            113: (self._bit_test_r, [6, 'c']),
            114: (self._bit_test_r, [6, 'd']),
            115: (self._bit_test_r, [6, 'e']),
            116: (self._bit_test_r, [6, 'h']),
            117: (self._bit_test_r, [6, 'l']),
            118: (self._bit_test_hlm, [6]),
            119: (self._bit_test_r, [6, 'a']),
            # BIT 7
            120: (self._bit_test_r, [7, 'b']),
            121: (self._bit_test_r, [7, 'c']),
            122: (self._bit_test_r, [7, 'd']),
            123: (self._bit_test_r, [7, 'e']),
            124: (self._bit_test_r, [7, 'h']),
            125: (self._bit_test_r, [7, 'l']),
            126: (self._bit_test_hlm, [7]),
            127: (self._bit_test_r, [7, 'a']),
            # RES 0
            128: (self._res_bit_r, [0, 'b']),
            129: (self._res_bit_r, [0, 'c']),
            130: (self._res_bit_r, [0, 'd']),
            131: (self._res_bit_r, [0, 'e']),
            132: (self._res_bit_r, [0, 'h']),
            133: (self._res_bit_r, [0, 'l']),
            134: (self._res_bit_hlm, [0]),
            135: (self._res_bit_r, [0, 'a']),
            # RES 1
            136: (self._res_bit_r, [1, 'b']),
            137: (self._res_bit_r, [1, 'c']),
            138: (self._res_bit_r, [1, 'd']),
            139: (self._res_bit_r, [1, 'e']),
            140: (self._res_bit_r, [1, 'h']),
            141: (self._res_bit_r, [1, 'l']),
            142: (self._res_bit_hlm, [1]),
            143: (self._res_bit_r, [1, 'a']),
            # RES 2
            144: (self._res_bit_r, [2, 'b']),
            145: (self._res_bit_r, [2, 'c']),
            146: (self._res_bit_r, [2, 'd']),
            147: (self._res_bit_r, [2, 'e']),
            148: (self._res_bit_r, [2, 'h']),
            149: (self._res_bit_r, [2, 'l']),
            150: (self._res_bit_hlm, [2]),
            151: (self._res_bit_r, [2, 'a']),
            # RES 3
            152: (self._res_bit_r, [3, 'b']),
            153: (self._res_bit_r, [3, 'c']),
            154: (self._res_bit_r, [3, 'd']),
            155: (self._res_bit_r, [3, 'e']),
            156: (self._res_bit_r, [3, 'h']),
            157: (self._res_bit_r, [3, 'l']),
            158: (self._res_bit_hlm, [3]),
            159: (self._res_bit_r, [3, 'a']),
            # RES 4
            160: (self._res_bit_r, [4, 'b']),
            161: (self._res_bit_r, [4, 'c']),
            162: (self._res_bit_r, [4, 'd']),
            163: (self._res_bit_r, [4, 'e']),
            164: (self._res_bit_r, [4, 'h']),
            165: (self._res_bit_r, [4, 'l']),
            166: (self._res_bit_hlm, [4]),
            167: (self._res_bit_r, [4, 'a']),
            # RES 5
            168: (self._res_bit_r, [5, 'b']),
            169: (self._res_bit_r, [5, 'c']),
            170: (self._res_bit_r, [5, 'd']),
            171: (self._res_bit_r, [5, 'e']),
            172: (self._res_bit_r, [5, 'h']),
            173: (self._res_bit_r, [5, 'l']),
            174: (self._res_bit_hlm, [5]),
            175: (self._res_bit_r, [5, 'a']),
            # RES 6
            176: (self._res_bit_r, [6, 'b']),
            177: (self._res_bit_r, [6, 'c']),
            178: (self._res_bit_r, [6, 'd']),
            179: (self._res_bit_r, [6, 'e']),
            180: (self._res_bit_r, [6, 'h']),
            181: (self._res_bit_r, [6, 'l']),
            182: (self._res_bit_hlm, [6]),
            183: (self._res_bit_r, [6, 'a']),
            # RES 7
            184: (self._res_bit_r, [7, 'b']),
            185: (self._res_bit_r, [7, 'c']),
            186: (self._res_bit_r, [7, 'd']),
            187: (self._res_bit_r, [7, 'e']),
            188: (self._res_bit_r, [7, 'h']),
            189: (self._res_bit_r, [7, 'l']),
            190: (self._res_bit_hlm, [7]),
            191: (self._res_bit_r, [7, 'a']),
            # SET 0
            192: (self._set_bit_r, [0, 'b']),
            193: (self._set_bit_r, [0, 'c']),
            194: (self._set_bit_r, [0, 'd']),
            195: (self._set_bit_r, [0, 'e']),
            196: (self._set_bit_r, [0, 'h']),
            197: (self._set_bit_r, [0, 'l']),
            198: (self._set_bit_hlm, [0]),
            199: (self._set_bit_r, [0, 'a']),
            # SET 1
            200: (self._set_bit_r, [1, 'b']),
            201: (self._set_bit_r, [1, 'c']),
            202: (self._set_bit_r, [1, 'd']),
            203: (self._set_bit_r, [1, 'e']),
            204: (self._set_bit_r, [1, 'h']),
            205: (self._set_bit_r, [1, 'l']),
            206: (self._set_bit_hlm, [1]),
            207: (self._set_bit_r, [1, 'a']),
            # SET 2
            208: (self._set_bit_r, [2, 'b']),
            209: (self._set_bit_r, [2, 'c']),
            210: (self._set_bit_r, [2, 'd']),
            211: (self._set_bit_r, [2, 'e']),
            212: (self._set_bit_r, [2, 'h']),
            213: (self._set_bit_r, [2, 'l']),
            214: (self._set_bit_hlm, [2]),
            215: (self._set_bit_r, [2, 'a']),
            # SET 3
            216: (self._set_bit_r, [3, 'b']),
            217: (self._set_bit_r, [3, 'c']),
            218: (self._set_bit_r, [3, 'd']),
            219: (self._set_bit_r, [3, 'e']),
            220: (self._set_bit_r, [3, 'h']),
            221: (self._set_bit_r, [3, 'l']),
            222: (self._set_bit_hlm, [3]),
            223: (self._set_bit_r, [3, 'a']),
            # SET 4
            224: (self._set_bit_r, [4, 'b']),
            225: (self._set_bit_r, [4, 'c']),
            226: (self._set_bit_r, [4, 'd']),
            227: (self._set_bit_r, [4, 'e']),
            228: (self._set_bit_r, [4, 'h']),
            229: (self._set_bit_r, [4, 'l']),
            230: (self._set_bit_hlm, [4]),
            231: (self._set_bit_r, [4, 'a']),
            # SET 5
            232: (self._set_bit_r, [5, 'b']),
            233: (self._set_bit_r, [5, 'c']),
            234: (self._set_bit_r, [5, 'd']),
            235: (self._set_bit_r, [5, 'e']),
            236: (self._set_bit_r, [5, 'h']),
            237: (self._set_bit_r, [5, 'l']),
            238: (self._set_bit_hlm, [5]),
            239: (self._set_bit_r, [5, 'a']),
            # SET 6
            240: (self._set_bit_r, [6, 'b']),
            241: (self._set_bit_r, [6, 'c']),
            242: (self._set_bit_r, [6, 'd']),
            243: (self._set_bit_r, [6, 'e']),
            244: (self._set_bit_r, [6, 'h']),
            245: (self._set_bit_r, [6, 'l']),
            246: (self._set_bit_hlm, [6]),
            247: (self._set_bit_r, [6, 'a']),
            # SET 7
            248: (self._set_bit_r, [7, 'b']),
            249: (self._set_bit_r, [7, 'c']),
            250: (self._set_bit_r, [7, 'd']),
            251: (self._set_bit_r, [7, 'e']),
            252: (self._set_bit_r, [7, 'h']),
            253: (self._set_bit_r, [7, 'l']),
            254: (self._set_bit_hlm, [7]),
            255: (self._set_bit_r, [7, 'a']),
        }
        self.opcode_table = [self.opcode_map[i] for i in range(256)]
        self.cb_table = [self.cb_map[i] for i in range(256)]
        self.pseudo_opcode_table = [
            self._fast_hram_compare_b_loop,
            self._fast_cp_hl_jr_nz_loop,
            self._fast_stat_mode_poll_loop,
            self._fast_ly_zero_loop,
            self._fast_rom_bit_decode_output_loop,
            self._fast_rom_bit_reader_helper,
        ]

    def reset_slow_diagnostics_window(self):
        """Clear per-frame slow-diagnostic counters."""
        self.slow_opcode_counts = [0] * 0x300
        self.slow_cb_opcode_counts = [0] * 256
        self.slow_pc_counts = {}
        self.slow_instruction_count = 0

    def consume_slow_diagnostics_window(self):
        """Return and reset per-frame slow-diagnostic counters."""
        snapshot = {
            'opcode_counts': self.slow_opcode_counts,
            'cb_opcode_counts': self.slow_cb_opcode_counts,
            'pc_counts': self.slow_pc_counts,
            'instructions': self.slow_instruction_count,
        }
        self.reset_slow_diagnostics_window()
        return snapshot

    def execute_next_operation(self):
        global my_counter
        registers = self.registers
        sys_interface = self.sys_interface
        gpu = sys_interface.gpu
        clock = self.clock
        trace_enabled = self.trace_enabled
        gb_doctor_test_mode = self.gb_doctor_test_mode
        if trace_enabled:
            my_counter += 1

        # Handle HALT state
        if self.halted:
            pending = (
                sys_interface.read_byte(0xFFFF)
                & sys_interface.read_byte(0xFF0F)
                & 0x1F
            )
            if not pending:
                m_cycles = min(
                    gpu.m_cycles_until_mode_transition(),
                    sys_interface.m_cycles_until_timer_interrupt(),
                )
                registers['m'] = m_cycles
                clock['m'] += m_cycles
                self.halt_m_cycles += m_cycles
                self._step_system_timer(sys_interface, m_cycles)
                gpu.step(m_cycles * 4)
                return 0
            self.halted = False

        if gb_doctor_test_mode:
            self.log_for_gameboy_dr(registers['pc'])

        # Interrupts are accepted at the next instruction boundary. The
        # boundary state is logged above, then execution continues at the
        # interrupt vector instead of the interrupted PC.
        if registers['ime']:
            memory = sys_interface.raw_memory
            if memory[0xFFFF] & memory[0xFF0F] & 0x1F:
                if self.handle_interrupts():
                    m_cycles = registers['m']
                    clock['m'] += m_cycles
                    self._step_system_timer(sys_interface, m_cycles)
                    gpu.step(m_cycles * 4)

        pc = registers['pc']
        if (
            self.diagnostics_enabled
            and self.pc_sample_start is not None
            and self.pc_sample_start <= pc <= self.pc_sample_end
        ):
            diagnostics = self.diagnostics
            diagnostics['pc_sample_hits'] = (
                diagnostics.get('pc_sample_hits', 0) + 1
            )
            pc_counts = diagnostics.setdefault('pc_sample_pcs', {})
            pc_counts[pc] = pc_counts.get(pc, 0) + 1
            samples = diagnostics.setdefault('pc_sample_registers', [])
            if len(samples) < self.pc_sample_limit:
                samples.append(
                    (
                        pc,
                        registers['a'],
                        registers['f'],
                        registers['b'],
                        registers['c'],
                        registers['d'],
                        registers['e'],
                        registers['h'],
                        registers['l'],
                        registers['sp'],
                        sys_interface.raw_memory[0xFF44],
                        gpu.linemode,
                    )
                )
        direct_rom = self.direct_rom
        if trace_enabled or self.opcode_counts is not None:
            decoded_rom_ops = None
        else:
            decoded_rom_ops = self.decoded_rom_ops
        if decoded_rom_ops is not None and pc < self.decoded_rom_ops_length:
            op = decoded_rom_ops[pc]
        elif direct_rom is not None and pc < 0x8000:
            op = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
        else:
            op = sys_interface.read_byte(pc)
        if self.opcode_counts is not None:
            self.opcode_counts[op] += 1
        if self.slow_diagnostics_enabled:
            if op < len(self.slow_opcode_counts):
                self.slow_opcode_counts[op] += 1
            pc_counts = self.slow_pc_counts
            pc_counts[pc] = pc_counts.get(pc, 0) + 1
            self.slow_instruction_count += 1
        executed_instructions = 1
        registers['pc'] = (pc + 1) & 0xFFFF

        if op < 0x100 and not INLINE_OPCODE_MASK[op]:
            opcode, args = self.opcode_table[op]
            opcode(*args)
        elif op >= OP_FAST_HRAM_POLL_LOOP_BASE:
            executed_instructions = self._fast_hram_poll_loop(
                pc, op - OP_FAST_HRAM_POLL_LOOP_BASE, sys_interface, gpu
            )
        elif op >= PSEUDO_OPCODE_BASE:
            executed_instructions = self.pseudo_opcode_table[
                op - PSEUDO_OPCODE_BASE
            ](pc, sys_interface, gpu)
        elif not trace_enabled and op == 0xF0:
            executed_instructions = self._fast_ldh_a_n(
                pc, direct_rom, sys_interface, gpu, gb_doctor_test_mode
            )
        elif not trace_enabled and op == 0xA7:
            a = registers['a']
            registers['f'] = FLAG_HALF_CARRY | (FLAG_ZERO if a == 0 else 0)
            registers['m'] = 1
        elif not trace_enabled and op == 0x28:
            pc = registers['pc']
            if direct_rom is not None and pc < 0x8000:
                i = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
            else:
                i = sys_interface.read_byte(pc)

            pc += 1
            if not (registers['f'] & FLAG_ZERO):
                registers['pc'] = pc & 0xFFFF
                registers['m'] = 2
            else:
                if i >= 0x80:
                    i -= 0x100
                registers['pc'] = (pc + i) & 0xFFFF
                registers['m'] = 3
        elif not trace_enabled and op == 0xB8:
            registers['f'] = CP_FLAG_TABLE[
                (registers['a'] << 8) | registers['b']
            ]
            registers['m'] = 1
        elif not trace_enabled and op == 0xBE:
            # Keep this very hot path inline: games commonly poll LY with
            # CP (HL); JR NZ,-3, and an extra helper call is measurable here.
            memory = sys_interface.raw_memory
            address = (registers['h'] << 8) | registers['l']
            if address == 0xFF44 and not sys_interface.memory.gb_doctor_test_mode:
                value = memory[0xFF44]
            else:
                value = sys_interface.read_byte(address)
            flags = CP_FLAG_TABLE[(registers['a'] << 8) | value]
            registers['f'] = flags

            can_fold_cp_hl_loop = (
                pc in self.cp_hl_jr_nz_loop_pcs
                and self.opcode_counts is None
                and not gb_doctor_test_mode
                and not self.enable_interrupts_next_cycle
                and not (memory[0xFFFF] & memory[0xFF0F] & 0x1F)
            )

            if not can_fold_cp_hl_loop:
                registers['m'] = 2
            else:
                executed_instructions = self._finish_fast_cp_hl_jr_nz_loop(
                    pc, sys_interface, gpu, memory, address, flags
                )
        elif not trace_enabled and op == 0x20:
            pc = registers['pc']
            if direct_rom is not None and pc < 0x8000:
                i = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
            else:
                i = sys_interface.read_byte(pc)

            pc += 1
            if registers['f'] & FLAG_ZERO:
                registers['pc'] = pc & 0xFFFF
                registers['m'] = 2
            else:
                if i >= 0x80:
                    i -= 0x100
                registers['pc'] = (pc + i) & 0xFFFF
                registers['m'] = 3
        elif not trace_enabled and op == 0x23:
            l = (registers['l'] + 1) & 0xFF
            registers['l'] = l
            if l == 0:
                registers['h'] = (registers['h'] + 1) & 0xFF
            registers['m'] = 2
        elif not trace_enabled and op == 0x05:
            val = registers['b']
            result = (val - 1) & 0xFF
            flags = (registers['f'] & FLAG_CARRY) | FLAG['sub']
            if result == 0:
                flags |= FLAG_ZERO
            if (val & 0xF) == 0:
                flags |= FLAG_HALF_CARRY
            registers['b'] = result
            registers['f'] = flags
            registers['m'] = 1
        elif not trace_enabled and op == 0x3D:
            if (
                self.opcode_counts is None
                and not self.enable_interrupts_next_cycle
                and pc >= 0xC000
            ):
                next_pc = (pc + 1) & 0xFFFF
                op1 = sys_interface.raw_memory[next_pc]
                op2 = sys_interface.raw_memory[(pc + 2) & 0xFFFF]
                if op1 == 0x20 and op2 == 0xFD:
                    executed_instructions = self._fast_dec_a_jr_nz_loop(
                        pc, sys_interface, gpu
                    )
                else:
                    self._dec_a()
            else:
                self._dec_a()
        elif not trace_enabled and op == 0x21:
            pc = registers['pc']
            if direct_rom is not None and pc < 0x8000:
                registers['l'] = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
                next_pc = pc + 1
                registers['h'] = (
                    direct_rom[next_pc] if next_pc < self.direct_rom_length else 0xFF
                )
            else:
                registers['l'] = sys_interface.read_byte(pc)
                registers['h'] = sys_interface.read_byte((pc + 1) & 0xFFFF)
            registers['pc'] = (pc + 2) & 0xFFFF
            registers['m'] = 3
        elif not trace_enabled and op == 0x12:
            address = (registers['d'] << 8) | registers['e']
            self._fast_write8(address, registers['a'], sys_interface)
            registers['m'] = 2
        elif not trace_enabled and op == 0x22:
            address = (registers['h'] << 8) | registers['l']
            self._fast_write8(address, registers['a'], sys_interface)
            l = (registers['l'] + 1) & 0xFF
            registers['l'] = l
            if l == 0:
                registers['h'] = (registers['h'] + 1) & 0xFF
            registers['m'] = 2
        elif not trace_enabled and op == 0x2A:
            address = (registers['h'] << 8) | registers['l']
            registers['a'] = self._fast_read8(address, direct_rom, sys_interface)
            l = (registers['l'] + 1) & 0xFF
            registers['l'] = l
            if l == 0:
                registers['h'] = (registers['h'] + 1) & 0xFF
            registers['m'] = 2
        elif not trace_enabled and op == 0xCB:
            pc = registers['pc']
            if direct_rom is not None and pc < 0x8000:
                cb_op = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
            else:
                cb_op = sys_interface.read_byte(pc)
            if self.cb_opcode_counts is not None:
                self.cb_opcode_counts[cb_op] += 1
            if self.slow_diagnostics_enabled:
                self.slow_cb_opcode_counts[cb_op] += 1
            registers['pc'] = (pc + 1) & 0xFFFF

            if cb_op == 0x46:
                if self.diagnostics_enabled:
                    diagnostics = self.diagnostics
                    diagnostics['cb46_count'] = (
                        diagnostics.get('cb46_count', 0) + 1
                    )
                    cb46_pcs = diagnostics.setdefault('cb46_pcs', {})
                    cb_pc = (pc - 1) & 0xFFFF
                    cb46_pcs[cb_pc] = cb46_pcs.get(cb_pc, 0) + 1
                address = (registers['h'] << 8) | registers['l']
                if (
                    0x8000 <= address <= 0x9FFF
                    or 0xC000 <= address <= 0xFEFF
                    or 0xFF80 <= address <= 0xFFFE
                ):
                    value = sys_interface.raw_memory[address]
                else:
                    value = self.read8(address)
                flags = (registers['f'] & FLAG_CARRY) | FLAG_HALF_CARRY
                if not (value & 0x01):
                    flags |= FLAG_ZERO
                registers['f'] = flags
                registers['m'] = 4
                if self.opcode_counts is None and not trace_enabled:
                    branch_pc = registers['pc']
                    if direct_rom is not None and branch_pc < 0x8000:
                        branch_op = (
                            direct_rom[branch_pc]
                            if branch_pc < self.direct_rom_length
                            else 0xFF
                        )
                    else:
                        branch_op = sys_interface.read_byte(branch_pc)

                    if branch_op == 0x28:
                        operand_pc = (branch_pc + 1) & 0xFFFF
                        if direct_rom is not None and operand_pc < 0x8000:
                            offset = (
                                direct_rom[operand_pc]
                                if operand_pc < self.direct_rom_length
                                else 0xFF
                            )
                        else:
                            offset = sys_interface.read_byte(operand_pc)
                        next_pc = (branch_pc + 2) & 0xFFFF
                        if flags & FLAG_ZERO:
                            if offset >= 0x80:
                                offset -= 0x100
                            registers['pc'] = (next_pc + offset) & 0xFFFF
                            registers['m'] = 7
                        else:
                            registers['pc'] = next_pc
                            registers['m'] = 6
                        executed_instructions = 2
                        if self.diagnostics_enabled:
                            diagnostics['cb46_branch_folded'] = (
                                diagnostics.get('cb46_branch_folded', 0) + 1
                            )
                    elif branch_op == 0xC2:
                        operand_pc = (branch_pc + 1) & 0xFFFF
                        if direct_rom is not None and operand_pc < 0x8000:
                            lo = (
                                direct_rom[operand_pc]
                                if operand_pc < self.direct_rom_length
                                else 0xFF
                            )
                            hi_pc = branch_pc + 2
                            hi = (
                                direct_rom[hi_pc]
                                if hi_pc < self.direct_rom_length
                                else 0xFF
                            )
                        else:
                            lo = sys_interface.read_byte(operand_pc)
                            hi = sys_interface.read_byte((branch_pc + 2) & 0xFFFF)
                        if flags & FLAG_ZERO:
                            registers['pc'] = (branch_pc + 3) & 0xFFFF
                            registers['m'] = 7
                        else:
                            registers['pc'] = (hi << 8) | lo
                            registers['m'] = 8
                        executed_instructions = 2
                        if self.diagnostics_enabled:
                            diagnostics['cb46_branch_folded'] = (
                                diagnostics.get('cb46_branch_folded', 0) + 1
                            )
            else:
                register_index = cb_op & 0x07
                if 0x40 <= cb_op < 0x80 and register_index != 6:
                    value = registers[CB_REGISTER_NAMES[register_index]]
                    flags = (registers['f'] & FLAG_CARRY) | FLAG_HALF_CARRY
                    if not value & (1 << ((cb_op >> 3) & 0x07)):
                        flags |= FLAG_ZERO
                    registers['f'] = flags
                    registers['m'] = 2
                else:
                    cb_handler, cb_args = self.cb_table[cb_op]
                    if cb_args:
                        cb_handler(*cb_args)
                    else:
                        cb_handler()
        else:
            opcode, args = self.opcode_table[op]
            opcode(*args)

        if trace_enabled:
            opcode, args = self.opcode_table[op]
            print(
                f"[TRACE] Exec {opcode.__name__:<15} "
                f"args: {str(args):<20} "
                f"m={registers['m']}, instr: {my_counter}"
            )
        m_cycles = registers['m']
        if m_cycles == 0:
            raise Exception("[ERROR] CPU executed an instruction with m=0 — GPU will desync!")
        clock['m'] += m_cycles
        memory = sys_interface.raw_memory
        divider_counter = sys_interface.divider_counter
        next_divider_counter = (divider_counter + m_cycles) & 0x3FFF
        div_value = next_divider_counter >> 6
        if not sys_interface.timer_enabled:
            sys_interface.divider_counter = next_divider_counter
            if memory[0xFF04] != div_value:
                memory[0xFF04] = div_value
        else:
            shift = sys_interface.timer_period_shift
            edge_count = (divider_counter + m_cycles) >> shift
            edge_count -= divider_counter >> shift
            if edge_count:
                tima = memory[0xFF05]
                tma = memory[0xFF06]
                for _ in range(edge_count):
                    if tima == 0xFF:
                        tima = tma
                        memory[0xFF0F] |= 0x04
                    else:
                        tima += 1
                memory[0xFF05] = tima

            sys_interface.divider_counter = next_divider_counter
            if memory[0xFF04] != div_value:
                memory[0xFF04] = div_value
        ppu_cycles = m_cycles * 4
        if memory[0xFF40] & 0x80:
            mode_clock = gpu._mode_clock
            next_mode_clock = mode_clock + ppu_cycles
            linemode = gpu.linemode
            if (
                (linemode == 0 and next_mode_clock < 204)
                or (linemode == 2 and next_mode_clock < 80)
                or (linemode == 3 and next_mode_clock < 172)
                or (
                    linemode == 1
                    and next_mode_clock < 456
                    and not (
                        memory[0xFF44] == 153
                        and not gpu._line153_ly_reset
                        and next_mode_clock >= 4
                    )
                )
            ):
                gpu._mode_clock = next_mode_clock
            else:
                gpu.step(ppu_cycles)

        # Handle delayed EI
        if self.enable_interrupts_next_cycle:
            registers['ime'] = 1
            self.enable_interrupts_next_cycle = False
        return executed_instructions

    def _fast_ldh_a_n(self, pc, direct_rom, sys_interface, gpu, gb_doctor_test_mode):
        """Fast path for LDH A,(n), including scanned HRAM wait loops."""
        registers = self.registers
        poll_loops = self.hram_poll_loop_ldh_offsets
        if (
            poll_loops
            and not gb_doctor_test_mode
            and self.opcode_counts is None
            and not self.enable_interrupts_next_cycle
        ):
            n = poll_loops.get(pc)
            if n is not None:
                return self._fast_hram_poll_loop(pc, n, sys_interface, gpu)

        compare_b_loop_pcs = self.hram_compare_b_loop_ldh_offsets
        if (
            compare_b_loop_pcs
            and not gb_doctor_test_mode
            and self.opcode_counts is None
            and not self.enable_interrupts_next_cycle
            and pc in compare_b_loop_pcs
        ):
            return self._fast_hram_compare_b_loop(pc, sys_interface, gpu)

        operand_pc = registers['pc']
        if direct_rom is not None and operand_pc < 0x8000:
            n = (
                direct_rom[operand_pc]
                if operand_pc < self.direct_rom_length
                else 0xFF
            )
        else:
            n = sys_interface.read_byte(operand_pc)

        registers['a'] = self._fast_ldh_value(n, sys_interface, gpu)
        registers['pc'] = (operand_pc + 1) & 0xFFFF
        registers['m'] = 3
        return 1

    def _fast_hram_poll_loop(self, pc, n, sys_interface, gpu):
        """Fast path for LDH A,(FF00+n); AND A; JR Z,-5."""
        registers = self.registers
        memory = sys_interface.raw_memory
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['pseudo_hram_poll_calls'] = (
                diagnostics.get('pseudo_hram_poll_calls', 0) + 1
            )
        if (
            not self.gb_doctor_test_mode
            and not self.enable_interrupts_next_cycle
            and not (memory[0xFFFF] & memory[0xFF0F] & 0x1F)
            and gpu.m_cycles_until_mode_transition() > 7
            and sys_interface.m_cycles_until_timer_interrupt() > 7
        ):
            a = memory[0xFF00 + n]
            registers['a'] = a
            registers['f'] = FLAG_HALF_CARRY | (FLAG_ZERO if a == 0 else 0)
            if a == 0:
                registers['pc'] = pc
                registers['m'] = 7
            else:
                registers['pc'] = (pc + 5) & 0xFFFF
                registers['m'] = 6
            if self.diagnostics_enabled:
                diagnostics['pseudo_hram_poll_instr'] = (
                    diagnostics.get('pseudo_hram_poll_instr', 0) + 3
                )
                diagnostics['pseudo_hram_poll_m_cycles'] = (
                    diagnostics.get('pseudo_hram_poll_m_cycles', 0)
                    + registers['m']
                )
            return 3

        operand_pc = registers['pc']
        registers['a'] = memory[0xFF00 + n]
        registers['pc'] = (operand_pc + 1) & 0xFFFF
        registers['m'] = 3
        if self.diagnostics_enabled:
            diagnostics['pseudo_hram_poll_fallbacks'] = (
                diagnostics.get('pseudo_hram_poll_fallbacks', 0) + 1
            )
        return 1

    def _fast_hram_compare_b_loop(self, pc, sys_interface, gpu):
        """Fast path for LDH A,(LY); CP B; JR NZ,-5."""
        registers = self.registers
        memory = sys_interface.raw_memory
        lcdc = memory[0xFF40]
        line = memory[0xFF44]
        diagnostics = None
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['pseudo_ly_compare_b_calls'] = (
                diagnostics.get('pseudo_ly_compare_b_calls', 0) + 1
            )
            ly_pcs = diagnostics.setdefault('pseudo_ly_compare_b_pcs', {})
            ly_pcs[pc] = ly_pcs.get(pc, 0) + 1
        if not (lcdc & 0x80):
            a = 0
        else:
            linemode = gpu.linemode
            mode_clock = gpu._mode_clock + 8
            if linemode == 0 and mode_clock >= 204:
                a = (line + 1) & 0xFF
            elif linemode == 1:
                line153_reset = gpu._line153_ly_reset
                if (
                    line == 153
                    and not line153_reset
                    and mode_clock >= 4
                ):
                    a = 0
                elif mode_clock >= 456 and not line153_reset:
                    a = (line + 1) & 0xFF
                else:
                    a = line
            else:
                a = line

        interrupts_can_fire = bool(registers['ime'])
        if (
            self.gb_doctor_test_mode
            or self.enable_interrupts_next_cycle
            or (
                interrupts_can_fire
                and (memory[0xFFFF] & memory[0xFF0F] & 0x1F)
            )
        ):
            registers['a'] = a
            registers['pc'] = (registers['pc'] + 1) & 0xFFFF
            registers['m'] = 3
            if diagnostics is not None:
                diagnostics['pseudo_ly_compare_b_fallbacks'] = (
                    diagnostics.get('pseudo_ly_compare_b_fallbacks', 0) + 1
                )
            return 1

        interrupt_enable = memory[0xFFFF]
        ppu_m_until = 0x10000
        if lcdc & 0x80:
            linemode = gpu.linemode
            mode_clock = gpu._mode_clock
            remaining = PPU_MODE_CYCLES[linemode] - mode_clock
            if (
                linemode == 1
                and not gpu._line153_ly_reset
                and line == 153
            ):
                line153_remaining = 4 - mode_clock
                if line153_remaining < remaining:
                    remaining = line153_remaining
            ppu_m_until = remaining >> 2
            if ppu_m_until < 1:
                ppu_m_until = 1

        timer_m_until = 0x10000
        if sys_interface.timer_enabled:
            period = 1 << sys_interface.timer_period_shift
            until_next_edge = period - (
                sys_interface.divider_counter & (period - 1)
            )
            edges_until_overflow = 0x100 - memory[0xFF05]
            timer_m_until = until_next_edge + (edges_until_overflow - 1) * period

        loop_boundary = ppu_m_until if ppu_m_until < timer_m_until else timer_m_until
        if lcdc & 0x80:
            if not (
                interrupts_can_fire
                and (interrupt_enable & memory[0xFF0F] & 0x07)
            ):
                # This intentionally does not stop at future STAT edges. The
                # folded instruction sequence is a pure LY wait loop, so
                # respecting pending interrupts and upcoming VBlank/timer
                # interrupts gives us the important CPU-observable boundaries
                # while avoiding thousands of Python wakeups per frame.
                ly_m_until = gpu.m_cycles_until_ly(registers['b'])
                interrupt_m_until = 0x10000
                if interrupts_can_fire and interrupt_enable & 0x01:
                    if line >= 144:
                        interrupt_m_until = 1
                    else:
                        interrupt_m_until = gpu.m_cycles_until_ly(144)
                if (
                    interrupts_can_fire
                    and interrupt_enable & 0x04
                    and timer_m_until < interrupt_m_until
                ):
                    interrupt_m_until = timer_m_until
                aggressive_boundary = (
                    ly_m_until
                    if ly_m_until < interrupt_m_until
                    else interrupt_m_until
                )
                if aggressive_boundary > loop_boundary:
                    loop_boundary = aggressive_boundary
                    if diagnostics is not None:
                        diagnostics['pseudo_ly_compare_b_aggressive_batches'] = (
                            diagnostics.get(
                                'pseudo_ly_compare_b_aggressive_batches',
                                0,
                            ) + 1
                        )
            elif diagnostics is not None:
                diagnostics['pseudo_ly_compare_b_aggressive_blocked_irq'] = (
                    diagnostics.get(
                        'pseudo_ly_compare_b_aggressive_blocked_irq',
                        0,
                    ) + 1
                )
        if loop_boundary <= 7:
            registers['a'] = a
            registers['pc'] = (registers['pc'] + 1) & 0xFFFF
            registers['m'] = 3
            if diagnostics is not None:
                diagnostics['pseudo_ly_compare_b_boundary_fallbacks'] = (
                    diagnostics.get(
                        'pseudo_ly_compare_b_boundary_fallbacks',
                        0,
                    ) + 1
                )
            return 1

        flags = CP_FLAG_TABLE[(a << 8) | registers['b']]
        registers['a'] = a
        registers['f'] = flags
        if flags & FLAG_ZERO:
            registers['pc'] = (pc + 5) & 0xFFFF
            registers['m'] = 6
            if diagnostics is not None:
                diagnostics['pseudo_ly_compare_b_exit_instr'] = (
                    diagnostics.get('pseudo_ly_compare_b_exit_instr', 0) + 3
                )
                diagnostics['pseudo_ly_compare_b_m_cycles'] = (
                    diagnostics.get('pseudo_ly_compare_b_m_cycles', 0) + 6
                )
            return 3

        loops = (loop_boundary - 1) // 7
        if loops < 1:
            loops = 1
        registers['pc'] = pc
        registers['m'] = loops * 7
        if diagnostics is not None:
            diagnostics['pseudo_ly_compare_b_loop_batches'] = (
                diagnostics.get('pseudo_ly_compare_b_loop_batches', 0) + 1
            )
            diagnostics['pseudo_ly_compare_b_loops'] = (
                diagnostics.get('pseudo_ly_compare_b_loops', 0) + loops
            )
            diagnostics['pseudo_ly_compare_b_m_cycles'] = (
                diagnostics.get('pseudo_ly_compare_b_m_cycles', 0)
                + registers['m']
            )
        return loops * 3

    def _fast_cp_hl_jr_nz_loop(self, pc, sys_interface, gpu):
        """Fast path for CP (HL); JR NZ,-3."""
        registers = self.registers
        memory = sys_interface.raw_memory
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['pseudo_cp_hl_calls'] = (
                diagnostics.get('pseudo_cp_hl_calls', 0) + 1
            )
        address = (registers['h'] << 8) | registers['l']
        if address == 0xFF44 and not sys_interface.memory.gb_doctor_test_mode:
            value = memory[0xFF44]
        else:
            value = sys_interface.read_byte(address)
        flags = CP_FLAG_TABLE[(registers['a'] << 8) | value]
        registers['f'] = flags

        if (
            self.gb_doctor_test_mode
            or self.enable_interrupts_next_cycle
            or (memory[0xFFFF] & memory[0xFF0F] & 0x1F)
        ):
            registers['m'] = 2
            return 1
        return self._finish_fast_cp_hl_jr_nz_loop(
            pc, sys_interface, gpu, memory, address, flags
        )

    def _fast_stat_mode_poll_loop(self, pc, sys_interface, gpu):
        """Fast path for LD A,(C); AND B; DEC A; JR NZ,-5 STAT polls."""
        registers = self.registers
        memory = sys_interface.raw_memory
        diagnostics = None
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['pseudo_stat_mode_poll_calls'] = (
                diagnostics.get('pseudo_stat_mode_poll_calls', 0) + 1
            )

        if registers['c'] != 0x41 or registers['b'] != 0x03:
            registers['a'] = sys_interface.read_byte(0xFF00 + registers['c'])
            registers['m'] = 2
            if diagnostics is not None:
                diagnostics['pseudo_stat_mode_poll_fallbacks'] = (
                    diagnostics.get('pseudo_stat_mode_poll_fallbacks', 0) + 1
                )
            return 1

        stat_mode = memory[0xFF41] & 0x03
        if stat_mode == 1:
            registers['a'] = 0
            registers['f'] = FLAG_ZERO | FLAG['sub']
            registers['pc'] = (pc + 5) & 0xFFFF
            registers['m'] = 6
            if diagnostics is not None:
                diagnostics['pseudo_stat_mode_poll_exits'] = (
                    diagnostics.get('pseudo_stat_mode_poll_exits', 0) + 1
                )
                diagnostics['pseudo_stat_mode_poll_m_cycles'] = (
                    diagnostics.get('pseudo_stat_mode_poll_m_cycles', 0) + 6
                )
            return 4

        interrupts_can_fire = bool(registers['ime'])
        if (
            self.gb_doctor_test_mode
            or self.enable_interrupts_next_cycle
            or (
                interrupts_can_fire
                and (memory[0xFFFF] & memory[0xFF0F] & 0x1F)
            )
        ):
            registers['a'] = memory[0xFF41]
            registers['m'] = 2
            if diagnostics is not None:
                diagnostics['pseudo_stat_mode_poll_fallbacks'] = (
                    diagnostics.get('pseudo_stat_mode_poll_fallbacks', 0) + 1
                )
            return 1

        ppu_m_until = gpu.m_cycles_until_linemode(1)
        timer_m_until = sys_interface.m_cycles_until_timer_interrupt()
        loop_boundary = ppu_m_until if ppu_m_until < timer_m_until else timer_m_until
        if loop_boundary <= 7:
            registers['a'] = memory[0xFF41]
            registers['m'] = 2
            if diagnostics is not None:
                diagnostics['pseudo_stat_mode_poll_boundary_fallbacks'] = (
                    diagnostics.get(
                        'pseudo_stat_mode_poll_boundary_fallbacks',
                        0,
                    ) + 1
                )
            return 1

        loops = (loop_boundary - 1) // 7
        if loops < 1:
            loops = 1
        registers['a'] = (stat_mode - 1) & 0xFF
        flags = FLAG['sub']
        if stat_mode == 0:
            flags |= FLAG_HALF_CARRY
        registers['f'] = flags
        registers['pc'] = pc
        registers['m'] = loops * 7
        if diagnostics is not None:
            diagnostics['pseudo_stat_mode_poll_batches'] = (
                diagnostics.get('pseudo_stat_mode_poll_batches', 0) + 1
            )
            diagnostics['pseudo_stat_mode_poll_loops'] = (
                diagnostics.get('pseudo_stat_mode_poll_loops', 0) + loops
            )
            diagnostics['pseudo_stat_mode_poll_m_cycles'] = (
                diagnostics.get('pseudo_stat_mode_poll_m_cycles', 0)
                + registers['m']
            )
        return loops * 4

    def _fast_ly_zero_loop(self, pc, sys_interface, gpu):
        """Fast path for LDH A,(LY); AND A; JR NZ,-5."""
        registers = self.registers
        memory = sys_interface.raw_memory
        lcdc = memory[0xFF40]
        line = memory[0xFF44]
        diagnostics = None
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['pseudo_ly_zero_calls'] = (
                diagnostics.get('pseudo_ly_zero_calls', 0) + 1
            )
            ly_zero_pcs = diagnostics.setdefault('pseudo_ly_zero_pcs', {})
            ly_zero_pcs[pc] = ly_zero_pcs.get(pc, 0) + 1

        if not (lcdc & 0x80):
            a = 0
        else:
            linemode = gpu.linemode
            mode_clock = gpu._mode_clock + 8
            if linemode == 0 and mode_clock >= 204:
                a = (line + 1) & 0xFF
            elif linemode == 1:
                line153_reset = gpu._line153_ly_reset
                if line == 153 and not line153_reset and mode_clock >= 4:
                    a = 0
                elif mode_clock >= 456 and not line153_reset:
                    a = (line + 1) & 0xFF
                else:
                    a = line
            else:
                a = line

        interrupts_can_fire = bool(registers['ime'])
        if (
            self.gb_doctor_test_mode
            or self.enable_interrupts_next_cycle
            or (
                interrupts_can_fire
                and (memory[0xFFFF] & memory[0xFF0F] & 0x1F)
            )
        ):
            registers['a'] = a
            registers['pc'] = (registers['pc'] + 1) & 0xFFFF
            registers['m'] = 3
            if diagnostics is not None:
                diagnostics['pseudo_ly_zero_fallbacks'] = (
                    diagnostics.get('pseudo_ly_zero_fallbacks', 0) + 1
                )
            return 1

        registers['a'] = a
        flags = FLAG_HALF_CARRY | (FLAG_ZERO if a == 0 else 0)
        if flags & FLAG_ZERO:
            registers['f'] = flags
            registers['pc'] = (pc + 5) & 0xFFFF
            registers['m'] = 6
            if diagnostics is not None:
                diagnostics['pseudo_ly_zero_exits'] = (
                    diagnostics.get('pseudo_ly_zero_exits', 0) + 1
                )
                diagnostics['pseudo_ly_zero_m_cycles'] = (
                    diagnostics.get('pseudo_ly_zero_m_cycles', 0) + 6
                )
            return 3

        ppu_m_until = 0x10000
        if lcdc & 0x80:
            linemode = gpu.linemode
            mode_clock = gpu._mode_clock
            remaining = PPU_MODE_CYCLES[linemode] - mode_clock
            if (
                linemode == 1
                and not gpu._line153_ly_reset
                and line == 153
            ):
                line153_remaining = 4 - mode_clock
                if line153_remaining < remaining:
                    remaining = line153_remaining
            ppu_m_until = remaining >> 2
            if ppu_m_until < 1:
                ppu_m_until = 1

        timer_m_until = sys_interface.m_cycles_until_timer_interrupt()
        loop_boundary = ppu_m_until if ppu_m_until < timer_m_until else timer_m_until
        interrupt_enable = memory[0xFFFF]
        if lcdc & 0x80:
            if not (
                interrupts_can_fire
                and (interrupt_enable & memory[0xFF0F] & 0x07)
            ):
                ly_m_until = gpu.m_cycles_until_ly(0)
                interrupt_m_until = 0x10000
                if interrupts_can_fire and interrupt_enable & 0x01:
                    if line >= 144:
                        interrupt_m_until = 1
                    else:
                        interrupt_m_until = gpu.m_cycles_until_ly(144)
                if (
                    interrupts_can_fire
                    and interrupt_enable & 0x04
                    and timer_m_until < interrupt_m_until
                ):
                    interrupt_m_until = timer_m_until
                aggressive_boundary = (
                    ly_m_until
                    if ly_m_until < interrupt_m_until
                    else interrupt_m_until
                )
                if aggressive_boundary > loop_boundary:
                    loop_boundary = aggressive_boundary
                    if diagnostics is not None:
                        diagnostics['pseudo_ly_zero_aggressive_batches'] = (
                            diagnostics.get(
                                'pseudo_ly_zero_aggressive_batches',
                                0,
                            ) + 1
                        )
            elif diagnostics is not None:
                diagnostics['pseudo_ly_zero_aggressive_blocked_irq'] = (
                    diagnostics.get(
                        'pseudo_ly_zero_aggressive_blocked_irq',
                        0,
                    ) + 1
                )

        if loop_boundary <= 7:
            registers['pc'] = (registers['pc'] + 1) & 0xFFFF
            registers['m'] = 3
            if diagnostics is not None:
                diagnostics['pseudo_ly_zero_boundary_fallbacks'] = (
                    diagnostics.get(
                        'pseudo_ly_zero_boundary_fallbacks',
                        0,
                    ) + 1
                )
            return 1

        loops = (loop_boundary - 1) // 7
        if loops < 1:
            loops = 1
        registers['f'] = flags
        registers['pc'] = pc
        registers['m'] = loops * 7
        if diagnostics is not None:
            diagnostics['pseudo_ly_zero_batches'] = (
                diagnostics.get('pseudo_ly_zero_batches', 0) + 1
            )
            diagnostics['pseudo_ly_zero_loops'] = (
                diagnostics.get('pseudo_ly_zero_loops', 0) + loops
            )
            diagnostics['pseudo_ly_zero_m_cycles'] = (
                diagnostics.get('pseudo_ly_zero_m_cycles', 0)
                + registers['m']
            )
        return loops * 3

    def _fast_rom_bit_decode_output_loop(self, pc, sys_interface, gpu):
        """Fold an exact ROM-table bit decoder and its byte-output tail.

        This matches a compact decompression inner loop used by some ROMs:

            LD H,$3F; LD A,(HL); DEC H; RL C; JR C,+3;
            DEC H; SWAP A; RLA; JR C,...

        The bit decoder selects a ROM/table byte by leaving its source address
        in HL. This helper then performs the following LD A,(HL); LD (DE),A;
        INC E tail and stops at either the next DEC B loop entry or the row
        boundary, where the routine's more complex outer bookkeeping resumes.
        """
        registers = self.registers
        if (
            self.gb_doctor_test_mode
            or self.enable_interrupts_next_cycle
            or registers['ime']
        ):
            return self._fallback_fast_rom_bit_decode_output_loop(pc)

        direct_rom = self.direct_rom
        direct_rom_length = self.direct_rom_length
        read_byte = sys_interface.read_byte

        def read_fast(address):
            if (
                direct_rom is not None
                and address < 0x8000
                and address < direct_rom_length
            ):
                return direct_rom[address]
            return read_byte(address)

        a = registers['a']
        f = registers['f']
        b = registers['b']
        c = registers['c']
        d = registers['d']
        e = registers['e']
        h = registers['h']
        l = registers['l']
        sp = registers['sp']
        m_cycles = 0
        instructions = 0
        iterations = 0
        max_iterations = 512

        while iterations < max_iterations:
            iterations += 1

            # 3A75: LD H,$3F
            h = 0x3F
            m_cycles += 2
            instructions += 1

            # 3A77: LD A,(HL)
            a = read_fast((h << 8) | l)
            m_cycles += 2
            instructions += 1

            # 3A78: DEC H
            old_h = h
            h = (h - 1) & 0xFF
            f = (f & FLAG_CARRY) | FLAG['sub']
            if h == 0:
                f |= FLAG_ZERO
            if (old_h & 0x0F) == 0:
                f |= FLAG_HALF_CARRY
            m_cycles += 1
            instructions += 1

            # 3A79: CB 11 / RL C
            carry_in = 1 if f & FLAG_CARRY else 0
            carry_out = c & 0x80
            c = ((c << 1) & 0xFF) | carry_in
            f = FLAG_CARRY if carry_out else 0
            if c == 0:
                f |= FLAG_ZERO
            m_cycles += 2
            instructions += 1

            # 3A7B: JR C,+3
            if f & FLAG_CARRY:
                m_cycles += 3
            else:
                m_cycles += 2
                # 3A7D: DEC H
                old_h = h
                h = (h - 1) & 0xFF
                f = (f & FLAG_CARRY) | FLAG['sub']
                if h == 0:
                    f |= FLAG_ZERO
                if (old_h & 0x0F) == 0:
                    f |= FLAG_HALF_CARRY
                m_cycles += 1

                # 3A7E: CB 37 / SWAP A
                a = ((a & 0x0F) << 4) | (a >> 4)
                f = FLAG_ZERO if a == 0 else 0
                m_cycles += 2
                instructions += 2
            instructions += 1

            # 3A80: RLA
            carry_in = 1 if f & FLAG_CARRY else 0
            carry_out = a & 0x80
            a = ((a << 1) & 0xFF) | carry_in
            f = FLAG_CARRY if carry_out else 0
            m_cycles += 1
            instructions += 1

            # 3A81: JR C,-18. If not taken, output byte is ready at 3A83.
            if not (f & FLAG_CARRY):
                m_cycles += 2
                instructions += 1
                # 3A83: LD A,(HL)
                a = read_fast((h << 8) | l)
                m_cycles += 2
                instructions += 1

                # 3A84: LD (DE),A
                self._fast_write8((d << 8) | e, a, sys_interface)
                m_cycles += 2
                instructions += 1

                # 3A85: INC E
                e = (e + 1) & 0xFF
                m_cycles += 1
                instructions += 1

                # 3A86: LD L,$FE
                l = 0xFE
                m_cycles += 2
                instructions += 1

                # 3A88: LD A,E
                a = e
                m_cycles += 1
                instructions += 1

                # 3A89: AND $0F
                a &= 0x0F
                f = FLAG_HALF_CARRY | (FLAG_ZERO if a == 0 else 0)
                m_cycles += 2
                instructions += 1

                if a != 0:
                    # 3A8B: JR NZ,-27 -> 3A72
                    m_cycles += 3
                    next_pc = pc - 3
                else:
                    # 3A8B: JR NZ not taken; outer row/block logic follows.
                    m_cycles += 2
                    next_pc = pc + 24
                instructions += 1

                registers['a'] = a
                registers['f'] = f
                registers['b'] = b
                registers['c'] = c
                registers['d'] = d
                registers['e'] = e
                registers['h'] = h
                registers['l'] = l
                registers['sp'] = sp
                registers['pc'] = next_pc & 0xFFFF
                registers['m'] = m_cycles
                if self.diagnostics_enabled:
                    diagnostics = self.diagnostics
                    diagnostics['pseudo_rom_bit_decode_calls'] = (
                        diagnostics.get('pseudo_rom_bit_decode_calls', 0) + 1
                    )
                    diagnostics['pseudo_rom_bit_decode_iterations'] = (
                        diagnostics.get('pseudo_rom_bit_decode_iterations', 0)
                        + iterations
                    )
                    diagnostics['pseudo_rom_bit_decode_m_cycles'] = (
                        diagnostics.get('pseudo_rom_bit_decode_m_cycles', 0)
                        + m_cycles
                    )
                    diagnostics['pseudo_rom_bit_decode_tail_writes'] = (
                        diagnostics.get('pseudo_rom_bit_decode_tail_writes', 0)
                        + 1
                    )
                    if a == 0:
                        diagnostics['pseudo_rom_bit_decode_row_exits'] = (
                            diagnostics.get(
                                'pseudo_rom_bit_decode_row_exits',
                                0,
                            ) + 1
                        )
                return instructions

            m_cycles += 3
            instructions += 1

            # 3A71: LD L,(HL)
            l = read_fast((h << 8) | l)
            m_cycles += 2
            instructions += 1

            # 3A72: DEC B
            old_b = b
            b = (b - 1) & 0xFF
            f = (f & FLAG_CARRY) | FLAG['sub']
            if b == 0:
                f |= FLAG_ZERO
            if (old_b & 0x0F) == 0:
                f |= FLAG_HALF_CARRY
            m_cycles += 1
            instructions += 1

            # 3A73: JR Z,-10
            if b != 0:
                m_cycles += 2
                instructions += 1
                continue

            m_cycles += 3
            instructions += 1

            # 3A6B: POP BC; 3A6C: DEC SP; 3A6D: LD B,$08; 3A6F: JR +4
            c = read_fast(sp)
            b = read_fast((sp + 1) & 0xFFFF)
            sp = (sp + 2) & 0xFFFF
            m_cycles += 3
            sp = (sp - 1) & 0xFFFF
            m_cycles += 2
            b = 0x08
            m_cycles += 2
            m_cycles += 3
            instructions += 4

        registers['a'] = a
        registers['f'] = f
        registers['b'] = b
        registers['c'] = c
        registers['d'] = d
        registers['e'] = e
        registers['h'] = h
        registers['l'] = l
        registers['sp'] = sp
        registers['pc'] = pc
        registers['m'] = m_cycles
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['pseudo_rom_bit_decode_limit_exits'] = (
                diagnostics.get('pseudo_rom_bit_decode_limit_exits', 0) + 1
            )
        return instructions

    def _fallback_fast_rom_bit_decode_output_loop(self, pc):
        """Execute the first instruction of the ROM bit decoder normally."""
        registers = self.registers
        direct_rom = self.direct_rom
        next_pc = pc + 1
        if direct_rom is not None and next_pc < self.direct_rom_length:
            registers['h'] = direct_rom[next_pc]
        else:
            registers['h'] = self.sys_interface.read_byte(next_pc & 0xFFFF)
        registers['pc'] = (pc + 2) & 0xFFFF
        registers['m'] = 2
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['pseudo_rom_bit_decode_fallbacks'] = (
                diagnostics.get('pseudo_rom_bit_decode_fallbacks', 0) + 1
            )
        return 1

    def _fast_rom_bit_reader_helper(self, pc, sys_interface, gpu):
        """Fold an exact ROM bitreader helper including its RET."""
        registers = self.registers
        if (
            self.gb_doctor_test_mode
            or self.enable_interrupts_next_cycle
        ):
            return self._fallback_fast_rom_bit_reader_helper(sys_interface)

        memory = sys_interface.raw_memory
        if registers['ime']:
            interrupt_enable = memory[0xFFFF]
            if interrupt_enable & memory[0xFF0F] & 0x1F:
                return self._fallback_fast_rom_bit_reader_helper(
                    sys_interface
                )

            interrupt_m_until = 0x10000
            if interrupt_enable & 0x01:
                line = memory[0xFF44]
                if line >= 144:
                    interrupt_m_until = 1
                else:
                    interrupt_m_until = gpu.m_cycles_until_ly(144)
            if interrupt_enable & 0x02:
                stat_m_until = gpu.m_cycles_until_mode_transition()
                if stat_m_until < interrupt_m_until:
                    interrupt_m_until = stat_m_until
            if interrupt_enable & 0x04:
                timer_m_until = sys_interface.m_cycles_until_timer_interrupt()
                if timer_m_until < interrupt_m_until:
                    interrupt_m_until = timer_m_until
            if interrupt_m_until <= 16:
                return self._fallback_fast_rom_bit_reader_helper(
                    sys_interface
                )

        direct_rom = self.direct_rom
        value = self._fast_read8(
            (registers['d'] << 8) | registers['e'],
            direct_rom,
            sys_interface,
        )

        # LD A,(DE); AND C
        a = value & registers['c']

        # SWAP C
        c = registers['c']
        c = ((c & 0x0F) << 4) | (c >> 4)
        registers['c'] = c

        # BIT 7,C after SWAP C. SWAP clears carry, so BIT preserves carry=0.
        if c & 0x80:
            flags = FLAG_HALF_CARRY
            # JR NZ,+3; INC DE; RET
            de = (((registers['d'] << 8) | registers['e']) + 1) & 0xFFFF
            registers['d'] = (de >> 8) & 0xFF
            registers['e'] = de & 0xFF
            m_cycles = 16
        else:
            flags = FLAG_ZERO | FLAG_HALF_CARRY
            # JR NZ not taken; SWAP A; RET
            a = ((a & 0x0F) << 4) | (a >> 4)
            flags = FLAG_ZERO if a == 0 else 0
            m_cycles = 15

        sp = registers['sp']
        lo = self._fast_read8(sp, direct_rom, sys_interface)
        hi = self._fast_read8((sp + 1) & 0xFFFF, direct_rom, sys_interface)
        registers['sp'] = (sp + 2) & 0xFFFF
        registers['pc'] = (hi << 8) | lo
        registers['a'] = a
        registers['f'] = flags
        registers['m'] = m_cycles
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['pseudo_rom_bit_reader_calls'] = (
                diagnostics.get('pseudo_rom_bit_reader_calls', 0) + 1
            )
            diagnostics['pseudo_rom_bit_reader_m_cycles'] = (
                diagnostics.get('pseudo_rom_bit_reader_m_cycles', 0) + m_cycles
            )
            if c & 0x80:
                diagnostics['pseudo_rom_bit_reader_de_increments'] = (
                    diagnostics.get('pseudo_rom_bit_reader_de_increments', 0)
                    + 1
                )
        return 7

    def _fallback_fast_rom_bit_reader_helper(self, sys_interface):
        """Execute the first instruction of the ROM bitreader normally."""
        registers = self.registers
        registers['a'] = self._fast_read8(
            (registers['d'] << 8) | registers['e'],
            self.direct_rom,
            sys_interface,
        )
        registers['m'] = 2
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['pseudo_rom_bit_reader_fallbacks'] = (
                diagnostics.get('pseudo_rom_bit_reader_fallbacks', 0) + 1
            )
        return 1

    def _finish_fast_cp_hl_jr_nz_loop(
        self, pc, sys_interface, gpu, memory, address, flags
    ):
        """Finish the timing-sensitive fold for CP (HL); JR NZ,-3."""
        registers = self.registers
        ppu_m_until = 0x10000
        if memory[0xFF40] & 0x80:
            remaining = PPU_MODE_CYCLES[gpu.linemode] - gpu._mode_clock
            if (
                gpu.linemode == 1
                and not gpu._line153_ly_reset
                and memory[0xFF44] == 153
            ):
                line153_remaining = 4 - gpu._mode_clock
                if line153_remaining < remaining:
                    remaining = line153_remaining
            ppu_m_until = max(1, remaining // 4)

        timer_m_until = 0x10000
        if sys_interface.timer_enabled:
            period = 1 << sys_interface.timer_period_shift
            until_next_edge = period - (
                sys_interface.divider_counter & (period - 1)
            )
            edges_until_overflow = 0x100 - memory[0xFF05]
            timer_m_until = until_next_edge + (edges_until_overflow - 1) * period

        loop_boundary = min(ppu_m_until, timer_m_until)
        if loop_boundary <= 5:
            registers['m'] = 2
            return 1
        if flags & FLAG_ZERO:
            registers['pc'] = (registers['pc'] + 2) & 0xFFFF
            registers['m'] = 4
            return 2
        if address == 0xFF44:
            loops = (loop_boundary - 1) // 5
            if loops < 1:
                loops = 1
            registers['pc'] = pc
            registers['m'] = loops * 5
            return loops * 2

        registers['pc'] = pc
        registers['m'] = 5
        return 2

    def _fast_dec_a_jr_nz_loop(self, pc, sys_interface, gpu):
        """Fast path for DEC A; JR NZ,-3 countdown loops in ROM/RAM/HRAM."""
        registers = self.registers
        memory = sys_interface.raw_memory
        diagnostics = None
        if self.diagnostics_enabled:
            diagnostics = self.diagnostics
            diagnostics['pseudo_dec_a_loop_calls'] = (
                diagnostics.get('pseudo_dec_a_loop_calls', 0) + 1
            )

        interrupts_can_fire = bool(registers['ime'])
        if (
            self.gb_doctor_test_mode
            or (
                interrupts_can_fire
                and (memory[0xFFFF] & memory[0xFF0F] & 0x1F)
            )
        ):
            self._dec_a()
            return 1

        ppu_m_until = 0x10000
        if memory[0xFF40] & 0x80:
            remaining = PPU_MODE_CYCLES[gpu.linemode] - gpu._mode_clock
            if (
                gpu.linemode == 1
                and not gpu._line153_ly_reset
                and memory[0xFF44] == 153
            ):
                line153_remaining = 4 - gpu._mode_clock
                if line153_remaining < remaining:
                    remaining = line153_remaining
            ppu_m_until = max(1, remaining // 4)

        timer_m_until = sys_interface.m_cycles_until_timer_interrupt()
        loop_boundary = ppu_m_until if ppu_m_until < timer_m_until else timer_m_until
        if loop_boundary <= 4:
            self._dec_a()
            return 1

        a = registers['a']
        iterations_until_zero = a if a else 256
        max_iterations = (loop_boundary - 1) // 4
        if max_iterations < 1:
            self._dec_a()
            return 1
        iterations = (
            iterations_until_zero
            if iterations_until_zero < max_iterations
            else max_iterations
        )

        old_a = a
        a = (a - iterations) & 0xFF
        registers['a'] = a
        flags = (registers['f'] & FLAG_CARRY) | FLAG['sub']
        if a == 0:
            flags |= FLAG_ZERO
        last_dec_input = (old_a - iterations + 1) & 0xFF
        if (last_dec_input & 0x0F) == 0:
            flags |= FLAG_HALF_CARRY
        registers['f'] = flags

        if iterations == iterations_until_zero:
            registers['pc'] = (pc + 3) & 0xFFFF
            registers['m'] = (iterations - 1) * 4 + 3
        else:
            registers['pc'] = pc
            registers['m'] = iterations * 4

        if diagnostics is not None:
            diagnostics['pseudo_dec_a_loop_iterations'] = (
                diagnostics.get('pseudo_dec_a_loop_iterations', 0)
                + iterations
            )
            diagnostics['pseudo_dec_a_loop_m_cycles'] = (
                diagnostics.get('pseudo_dec_a_loop_m_cycles', 0)
                + registers['m']
            )
        return iterations * 2

    def _fast_ldh_value(self, n, sys_interface, gpu):
        """Read the LDH target, including special LY timing behavior."""
        if n >= 0x80:
            return sys_interface.raw_memory[0xFF00 + n]
        if n == 0:
            return sys_interface.joypad.read()
        if self.gb_doctor_test_mode and n == 0x44:
            return 0x90
        if n != 0x44:
            return sys_interface.raw_memory[0xFF00 + n]

        memory = sys_interface.raw_memory
        line = memory[0xFF44]
        if not (memory[0xFF40] & 0x80):
            return 0

        mode_clock = gpu._mode_clock + 8
        if gpu.linemode == 0 and mode_clock >= 204:
            return (line + 1) & 0xFF
        if gpu.linemode == 1:
            if line == 153 and not gpu._line153_ly_reset and mode_clock >= 4:
                return 0
            if mode_clock >= 456 and not gpu._line153_ly_reset:
                return (line + 1) & 0xFF
        return line

    @staticmethod
    def _fast_write8(address, value, sys_interface):
        """Write through the common RAM/HRAM fast path when safe."""
        if (
            sys_interface.cgb_mode
            and (0xD000 <= address <= 0xDFFF or 0xF000 <= address <= 0xFDFF)
        ):
            sys_interface.write_byte(address, value)
        elif 0xC000 <= address <= 0xFDFF or 0xFF80 <= address <= 0xFFFE:
            sys_interface.raw_memory[address] = value
        else:
            sys_interface.write_byte(address, value)

    def _fast_read8(self, address, direct_rom, sys_interface):
        """Read through the common ROM/RAM/HRAM fast path when safe."""
        if direct_rom is not None and address < self.direct_rom_length:
            return direct_rom[address]
        if (
            sys_interface.cgb_mode
            and (0xD000 <= address <= 0xDFFF or 0xF000 <= address <= 0xFDFF)
        ):
            return sys_interface.read_byte(address)
        if 0xC000 <= address <= 0xFDFF or 0xFF80 <= address <= 0xFFFE:
            return sys_interface.raw_memory[address]
        return sys_interface.read_byte(address)

    @staticmethod
    def _step_system_timer(sys_interface, m_cycles):
        """Advance DIV/TIMA in the CPU hot path without method dispatch."""
        memory = sys_interface.raw_memory
        divider_counter = sys_interface.divider_counter
        next_divider_counter = (divider_counter + m_cycles) & 0x3FFF
        div_value = next_divider_counter >> 6
        if not sys_interface.timer_enabled:
            sys_interface.divider_counter = next_divider_counter
            if memory[0xFF04] != div_value:
                memory[0xFF04] = div_value
            return

        shift = sys_interface.timer_period_shift
        edge_count = (divider_counter + m_cycles) >> shift
        edge_count -= divider_counter >> shift
        if edge_count:
            tima = memory[0xFF05]
            tma = memory[0xFF06]
            for _ in range(edge_count):
                if tima == 0xFF:
                    tima = tma
                    memory[0xFF0F] |= 0x04
                else:
                    tima += 1
            memory[0xFF05] = tima

        sys_interface.divider_counter = next_divider_counter
        if memory[0xFF04] != div_value:
            memory[0xFF04] = div_value

    def log_for_gameboy_dr(self, pc):
        pcmem = [self.read8(pc + i) if (pc + i) < 0x10000 else 0 for i in range(4)]
        log_line = (
            f"A:{self.registers['a']:02X} F:{self.registers['f']:02X} "
            f"B:{self.registers['b']:02X} C:{self.registers['c']:02X} "
            f"D:{self.registers['d']:02X} E:{self.registers['e']:02X} "
            f"H:{self.registers['h']:02X} L:{self.registers['l']:02X} "
            f"SP:{self.registers['sp']:04X} PC:{pc:04X} "
            f"PCMEM:{','.join(f'{b:02X}' for b in pcmem)}"
        )
        self.log_dump.append(log_line)

    def execute_specific_instruction(self, op):
        """Execute an instruction (for testing)."""
        instruction = self.opcode_map[op]
        if self.trace_enabled:
            print(instruction)
        opcode, args = instruction[0], instruction[1]
        opcode(*args)
        self._inc_clock()

    def handle_interrupts(self):
        registers = self.registers
        if not registers['ime']:
            return False  # interrupts globally disabled

        memory = self.sys_interface.raw_memory
        interrupt_enable = memory[0xFFFF]
        interrupt_flags = memory[0xFF0F]
        triggered = interrupt_enable & interrupt_flags
        if triggered:
            if self.trace_enabled:
                print("[INTERRUPT] Interrupt triggered with flags: ", interrupt_flags)
                print(
                    f"[DEBUG PRE-INTERRUPT ] "
                    f"PC={registers['pc']:04X}, "
                    f"SP={registers['sp']:04X}"
                )
            for bit, address in enumerate([0x40, 0x48, 0x50, 0x58, 0x60]):
                if triggered & (1 << bit):
                    self._execute_interrupt(bit, address)
                    if self.trace_enabled:
                        print(
                            f"[DEBUG POST-INTERRUPT] "
                            f"PC={registers['pc']:04X}, "
                            f"SP={registers['sp']:04X}"
                        )
                    return True  # only handle one interrupt per boundary
        return False

    def _execute_interrupt(self, bit, address):
        self.registers['ime'] = 0  # disable further interrupts
        interrupt_flags = self.sys_interface.read_byte(0xFF0F)
        interrupt_flags &= ~(1 << bit)  # clear handled interrupt
        self.sys_interface.write_byte(0xFF0F, interrupt_flags)

        # Push current PC to stack
        self.registers['sp'] = (self.registers['sp'] - 2) & 0xFFFF
        self.write16(self.registers['sp'], self.registers['pc'])

        # Jump to interrupt vector
        self.registers['pc'] = address

        # Interrupt takes 5 CPU cycles (20 clock cycles)
        self.registers['m'] = 5

    def reset(self):
        """Reset registers."""
        self.halt_m_cycles = 0
        for k in self.clock.items():
            self.clock[k] = 0
        for k in self.registers.items():
            self.registers[k] = 0

    def read8(self, address):
        """Return a byte from memory at address."""
        address &= 0xFFFF
        direct_rom = self.direct_rom
        if direct_rom is not None and address < self.direct_rom_length:
            return direct_rom[address]
        sys_interface = self.sys_interface
        if (
            sys_interface.cgb_mode
            and (0xD000 <= address <= 0xDFFF or 0xF000 <= address <= 0xFDFF)
        ):
            return sys_interface.read_byte(address)
        if (
            0xC000 <= address <= 0xFDFF
            or 0xFF80 <= address <= 0xFFFE
        ):
            return sys_interface.raw_memory[address]
        return sys_interface.read_byte(address)

    def write8(self, address, val):
        """Write a byte to memory at address."""
        sys_interface = self.sys_interface
        if (
            sys_interface.cgb_mode
            and (0xD000 <= address <= 0xDFFF or 0xF000 <= address <= 0xFDFF)
        ):
            sys_interface.write_byte(address, val)
            return
        if (
            0xC000 <= address <= 0xFDFF
            or 0xFF80 <= address <= 0xFFFE
        ):
            sys_interface.raw_memory[address] = val
            return
        sys_interface.write_byte(address, val)

    def read16(self, address):
        """Return a word(16-bits) from memory."""
        address &= 0xFFFF
        direct_rom = self.direct_rom
        if (
            direct_rom is not None
            and address + 1 < self.direct_rom_length
        ):
            return direct_rom[address] | (direct_rom[address + 1] << 8)
        sys_interface = self.sys_interface
        if (
            0xC000 <= address < 0xFDFF
            or 0xFF80 <= address < 0xFFFE
        ):
            memory = sys_interface.raw_memory
            return memory[address] | (memory[address + 1] << 8)
        return sys_interface.read_word(address)

    def write16(self, address, val):
        """Write a word to memory at address."""
        self.write8(address, val & 0xFF)
        self.write8((address + 1) & 0xFFFF, (val >> 8) & 0xFF)

    @staticmethod
    def signed8(n):
        """Convert 8-bit unsigned value to signed integer."""
        return n - 0x100 if n >= 0x80 else n

    def _call_cb_op(self):
        """Call an opcode in the cb map."""
        registers = self.registers
        pc = registers['pc']
        direct_rom = self.direct_rom
        if direct_rom is not None and pc < 0x8000:
            i = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
        else:
            i = self.sys_interface.read_byte(pc)
        if self.cb_opcode_counts is not None:
            self.cb_opcode_counts[i] += 1
        registers['pc'] = (pc + 1) & 0xFFFF

        if i == 0x46:
            addr = (registers['h'] << 8) | registers['l']
            if (
                0x8000 <= addr <= 0x9FFF
                or 0xC000 <= addr <= 0xFEFF
                or 0xFF80 <= addr <= 0xFFFE
            ):
                value = self.sys_interface.raw_memory[addr]
            else:
                value = self.read8(addr)
            flags = (registers['f'] & FLAG_CARRY) | FLAG_HALF_CARRY
            if not (value & 0x01):
                flags |= FLAG_ZERO
            registers['f'] = flags
            registers['m'] = 4
            return

        register_index = i & 0x07
        if 0x40 <= i < 0x80 and register_index != 6:
            value = registers[CB_REGISTER_NAMES[register_index]]
            flags = (registers['f'] & FLAG_CARRY) | FLAG_HALF_CARRY
            if not value & (1 << ((i >> 3) & 0x07)):
                flags |= FLAG_ZERO
            registers['f'] = flags
            registers['m'] = 2
            return

        op, args = self.cb_table[i]
        if args:
            op(*args)
        else:
            op()

    def _inc_clock(self):
        """Increment clock registers and step GPU."""
        registers = self.registers
        m_cycles = registers['m']
        if m_cycles == 0:
            raise Exception("[ERROR] CPU executed an instruction with m=0 — GPU will desync!")

        self.clock['m'] += m_cycles
        sys_interface = self.sys_interface
        if sys_interface is None:
            return

        sys_interface.step(m_cycles)
        # print(f"[CLOCK] +{self.registers['m']} m-cycles → total={self.clock['m']}")
        sys_interface.gpu.step(m_cycles * 4)  # 1 m = 4 cycles

    def _toggle_flag(self, flag_value):
        self.registers['f'] |= flag_value

    @staticmethod
    def _raise_opcode_unimplemented():
        print("counter:", my_counter)
        raise Exception("Opcode unimplemented!")

    def _raise_cb_op_unimplemented(self, fn_name):
        print("cb code", fn_name, "unimplemented!")
        self._raise_opcode_unimplemented()

    # Opcodes
    # ----------------------------
    def _nop(self):
        """NOP opcode."""
        self.registers['m'] = 1

    # Loads
    def _ld_rr(self, r1, r2):
        """Load value r2 into r1."""
        self.registers[r1] = self.registers[r2]
        self.registers['m'] = 1

    def _ld_a_b(self):
        """Load B into A, specialized for opcode 0x78."""
        registers = self.registers
        registers['a'] = registers['b']
        registers['m'] = 1

    def _ld_a_l(self):
        """Load L into A, specialized for opcode 0x7D."""
        registers = self.registers
        registers['a'] = registers['l']
        registers['m'] = 1

    def _ld_rn(self, r):
        """Load mem @ pc into register r."""
        registers = self.registers
        pc = registers['pc']
        direct_rom = self.direct_rom
        if direct_rom is not None and pc < self.direct_rom_length:
            value = direct_rom[pc]
        else:
            value = self.sys_interface.read_byte(pc)
        registers[r] = value
        registers['pc'] = (pc + 1) & 0xFFFF
        registers['m'] = 2

    def _ld_r_hlm(self, r):
        """Load mem @ HL into registers[r]."""
        read_val = self.read8((self.registers['h'] << 8) + self.registers['l'])
        self.registers[r] = read_val
        self.registers['m'] = 2

    def _ld_a_hlm(self):
        """Load mem @ HL into A, specialized for opcode 0x7E."""
        registers = self.registers
        registers['a'] = self.read8((registers['h'] << 8) | registers['l'])
        registers['m'] = 2

    def _ld_hlm_r(self, r):
        """Load registers[r] into mem @ HL."""
        address = (self.registers['h'] << 8) + self.registers['l']
        self.write8(address, self.registers[r])
        self.registers['m'] = 2

    def _ld_hlm_n(self):
        """Load mem @ pc into mem @ HL."""
        value = self.read8(self.registers['pc'])
        address = (self.registers['h'] << 8) + self.registers['l']
        self.write8(address, value)
        self.registers['pc'] += 1
        self.registers['m'] = 3

    def _ld_r1r2m_a(self, r1, r2):
        """Load registers[a] into mem @ BC."""
        address = (self.registers[r1] << 8) + self.registers[r2]
        self.write8(address, self.registers['a'])
        self.registers['m'] = 2

    def _ld_de_a(self):
        """Load A into mem @ DE, specialized for opcode 0x12."""
        registers = self.registers
        address = (registers['d'] << 8) | registers['e']
        sys_interface = self.sys_interface
        if (
            sys_interface.cgb_mode
            and (0xD000 <= address <= 0xDFFF or 0xF000 <= address <= 0xFDFF)
        ):
            sys_interface.write_byte(address, registers['a'])
        elif (
            0xC000 <= address <= 0xFDFF
            or 0xFF80 <= address <= 0xFFFE
        ):
            sys_interface.raw_memory[address] = registers['a']
        else:
            sys_interface.write_byte(address, registers['a'])
        registers['m'] = 2

    def _ld_nn_a(self):
        """Load byte registers['a'] into mem @ 16-bit address.

        address = mem (16-bit) @ registers[pc]
        """
        registers = self.registers
        pc = registers['pc']
        direct_rom = self.direct_rom
        if direct_rom is not None and pc + 1 < self.direct_rom_length:
            address = direct_rom[pc] | (direct_rom[pc + 1] << 8)
        else:
            address = self.sys_interface.read_word(pc)
        sys_interface = self.sys_interface
        if (
            sys_interface.cgb_mode
            and (0xD000 <= address <= 0xDFFF or 0xF000 <= address <= 0xFDFF)
        ):
            sys_interface.write_byte(address, registers['a'])
        elif (
            0xC000 <= address <= 0xFDFF
            or 0xFF80 <= address <= 0xFFFE
        ):
            sys_interface.raw_memory[address] = registers['a']
        else:
            sys_interface.write_byte(address, registers['a'])
        registers['pc'] = (pc + 2) & 0xFFFF
        registers['m'] = 4

    def _ld_a_r1r2m(self, r1, r2):
        """Load mem @ r1r2 into registers[a]."""
        address = (self.registers[r1] << 8) + self.registers[r2]
        self.registers['a'] = self.read8(address)
        self.registers['m'] = 2

    def _ld_a_nn(self):
        """Load byte @ address into registers[a].

        address = mem (16-bit) @ registers[pc]
        """
        registers = self.registers
        pc = registers['pc']
        direct_rom = self.direct_rom
        if direct_rom is not None and pc + 1 < self.direct_rom_length:
            address = direct_rom[pc] | (direct_rom[pc + 1] << 8)
        else:
            address = self.sys_interface.read_word(pc)
        if direct_rom is not None and address < self.direct_rom_length:
            registers['a'] = direct_rom[address]
        else:
            sys_interface = self.sys_interface
            if (
                sys_interface.cgb_mode
                and (0xD000 <= address <= 0xDFFF or 0xF000 <= address <= 0xFDFF)
            ):
                registers['a'] = sys_interface.read_byte(address)
            elif (
                0xC000 <= address <= 0xFDFF
                or 0xFF80 <= address <= 0xFFFE
            ):
                registers['a'] = sys_interface.raw_memory[address]
            else:
                registers['a'] = sys_interface.read_byte(address)
        registers['pc'] = (pc + 2) & 0xFFFF
        registers['m'] = 4

    def _ld_r1r2_nn(self, r1, r2):
        """Load 16-bit immediate value into two 8-bit registers."""
        self.registers[r2] = self.read8(self.registers['pc'])
        self.registers[r1] = self.read8(self.registers['pc'] + 1)
        self.registers['pc'] += 2
        self.registers['m'] = 3

    def _ld_hl_nn(self):
        """Load 16-bit immediate into HL, specialized for opcode 0x21."""
        registers = self.registers
        pc = registers['pc']
        direct_rom = self.direct_rom
        if direct_rom is not None and pc + 1 < self.direct_rom_length:
            registers['l'] = direct_rom[pc]
            registers['h'] = direct_rom[pc + 1]
        else:
            registers['l'] = self.read8(pc)
            registers['h'] = self.read8(pc + 1)
        registers['pc'] = (pc + 2) & 0xFFFF
        registers['m'] = 3

    def _ld_sp_nn(self):
        """Load 16-bit immediate value into stack pointer."""
        self.registers['sp'] = self.read16(self.registers['pc'])
        self.registers['pc'] += 2
        self.registers['m'] = 3

    def _ld_nn_sp(self):
        """Load SP into mem @ address (mm)."""
        address = self.read16(self.registers['pc'])
        self.write16(address, self.registers['sp'])
        self.registers['pc'] += 2
        self.registers['m'] = 5

    def _ld_hlmi_a(self):
        """Put A into memory address HL. Increment HL.

        Same as: LD (HL),A - INC HL
        """
        registers = self.registers
        address = (registers['h'] << 8) | registers['l']
        sys_interface = self.sys_interface
        if (
            sys_interface.cgb_mode
            and (0xD000 <= address <= 0xDFFF or 0xF000 <= address <= 0xFDFF)
        ):
            sys_interface.write_byte(address, registers['a'])
        elif (
            0xC000 <= address <= 0xFDFF
            or 0xFF80 <= address <= 0xFFFE
        ):
            sys_interface.raw_memory[address] = registers['a']
        else:
            sys_interface.write_byte(address, registers['a'])
        l = (registers['l'] + 1) & 0xFF
        registers['l'] = l
        if l == 0:
            registers['h'] = (registers['h'] + 1) & 0xFF
        registers['m'] = 2

    def _ld_hlmd_a(self):
        """Put A into memory address HL. Decrement HL.

        Same as: LD (HL),A - DEC HL
        """
        address = (self.registers['h'] << 8) + self.registers['l']
        self.write8(address, self.registers['a'])
        self._dec_r_r('h', 'l', m=2)

    def _ld_a_hl_i(self):
        """Load mem @ hl into reg a and increment."""
        registers = self.registers
        address = (registers['h'] << 8) | registers['l']
        direct_rom = self.direct_rom
        if direct_rom is not None and address < self.direct_rom_length:
            registers['a'] = direct_rom[address]
        else:
            sys_interface = self.sys_interface
            if (
                sys_interface.cgb_mode
                and (0xD000 <= address <= 0xDFFF or 0xF000 <= address <= 0xFDFF)
            ):
                registers['a'] = sys_interface.read_byte(address)
            elif (
                0xC000 <= address <= 0xFDFF
                or 0xFF80 <= address <= 0xFFFE
            ):
                registers['a'] = sys_interface.raw_memory[address]
            else:
                registers['a'] = sys_interface.read_byte(address)
        l = (registers['l'] + 1) & 0xFF
        registers['l'] = l
        if l == 0:
            registers['h'] = (registers['h'] + 1) & 0xFF
        registers['m'] = 2

    def _ld_a_hl_d(self):
        """Load mem @ hl into reg a and decrement."""
        address = (self.registers['h'] << 8) + self.registers['l']
        self.registers['a'] = self.read8(address)
        self._dec_r_r('h', 'l', m=2)

    def _ldh_a_n(self):
        """Put mem @ address $FF00+n into register a."""
        registers = self.registers
        sys_interface = self.sys_interface
        pc = registers['pc']
        direct_rom = self.direct_rom
        if direct_rom is not None and pc < 0x8000:
            n = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
        else:
            n = sys_interface.read_byte(pc)

        if n == 0:
            registers['a'] = sys_interface.joypad.read()
        elif self.gb_doctor_test_mode and n == 0x44:
            registers['a'] = 0x90
        elif n == 0x44:
            memory = sys_interface.raw_memory
            line = memory[0xFF44]
            if not (memory[0xFF40] & 0x80):
                registers['a'] = 0
            else:
                gpu = sys_interface.gpu
                mode_clock = gpu._mode_clock + 8
                if gpu.linemode == 0 and mode_clock >= 204:
                    registers['a'] = (line + 1) & 0xFF
                elif gpu.linemode == 1:
                    if (
                        line == 153
                        and not gpu._line153_ly_reset
                        and mode_clock >= 4
                    ):
                        registers['a'] = 0
                    elif mode_clock >= 456 and not gpu._line153_ly_reset:
                        registers['a'] = (line + 1) & 0xFF
                    else:
                        registers['a'] = line
                else:
                    registers['a'] = line
        else:
            registers['a'] = sys_interface.raw_memory[0xFF00 + n]
        registers['pc'] = pc + 1
        registers['m'] = 3

    def _ldh_n_a(self):
        """Put register A into mem @ address $FF00+n."""
        registers = self.registers
        sys_interface = self.sys_interface
        pc = registers['pc']
        direct_rom = self.direct_rom
        if direct_rom is not None and pc < 0x8000:
            n = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
        else:
            n = sys_interface.read_byte(pc)
        if n >= 0x80:
            sys_interface.raw_memory[0xFF00 + n] = registers['a']
        else:
            sys_interface.write_byte(0xFF00 + n, registers['a'])
        registers['pc'] = pc + 1
        registers['m'] = 3

    def _ld_a_c(self):
        """Put value @ address $FF00+C into register A."""
        self.registers['a'] = self.read8(0xFF00 + self.registers['c'])
        self.registers['m'] = 2

    def _ld_c_a(self):
        """Put A into mem @ address $FF00+C (correct)."""
        self.write8(0xFF00 + self.registers['c'], self.registers['a'])
        self.registers['m'] = 2

    def _ld_hl_sp_n(self):
        """LD HL, SP+n (signed)"""
        n = self.read8(self.registers['pc'])
        if n > 127:
            n = n - 256
        self.registers['pc'] += 1

        result = (self.registers['sp'] + n) & 0xFFFF

        self.registers['f'] = 0  # Z = 0, N = 0

        if ((self.registers['sp'] & 0xF) + (n & 0xF)) > 0xF:
            self.registers['f'] |= FLAG['half-carry']
        if ((self.registers['sp'] & 0xFF) + (n & 0xFF)) > 0xFF:
            self.registers['f'] |= FLAG['carry']

        self.registers['h'] = (result >> 8) & 0xFF
        self.registers['l'] = result & 0xFF
        self.registers['m'] = 3

    def _ld_sp_hl(self):
        """Put HL into SP."""
        h_shift = (self.registers['h'] << 8)
        self.registers['sp'] = h_shift + self.registers['l']
        self.registers['m'] = 2

    # Jumps
    def _jp_nn(self):
        """Jump to two byte immediate value."""
        self.registers['pc'] = self.read16(self.registers['pc'])
        self.registers['m'] = 4

    def _jp_cc_nn(self, and_val, flag_check_value):
        """Jump to address n if condition is true.

        cc = NZ, Jump if Z flag is reset.
        cc = Z, Jump if Z flag is set.
        cc = NC, Jump if C flag is reset.
        cc = C, Jump if C flag is set.
        nn = two byte immediate value. (LS byte first.)
        """
        self.registers['m'] = 3
        if (self.registers['f'] & and_val) == flag_check_value:
            self.registers['pc'] = self.read16(self.registers['pc'])
            self.registers['m'] += 1
        else:
            self.registers['pc'] += 2

    def _jp_hl(self):
        """Jump to address in HL."""
        self.registers['pc'] = (self.registers['h'] << 8) | self.registers['l']
        self.registers['m'] = 1

    def _jr_n(self):
        """Add signed immediate value to current address and jump to it."""
        i = self.signed8(self.read8(self.registers['pc']))
        self.registers['pc'] += 1
        self.registers['pc'] = (self.registers['pc'] + i) & 0xFFFF
        self.registers['m'] = 3

    def _jr_cc_n(self, and_val, flag_check_value):
        """Conditional relative jump

        If Z flag reset, add n to current address and jump to it.
        n = one byte signed immediate value
        """
        registers = self.registers
        pc = registers['pc']
        sys_interface = self.sys_interface
        direct_rom = self.direct_rom
        if direct_rom is not None and pc < 0x8000:
            i = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
        else:
            i = sys_interface.read_byte(pc)
        if i >= 0x80:
            i -= 0x100
        pc += 1
        registers['pc'] = pc  # Advance PC past the immediate byte
        registers['m'] = 2

        if (registers['f'] & and_val) == flag_check_value:
            registers['pc'] = (pc + i) & 0xFFFF
            registers['m'] = 3

    def _jr_nz_n(self):
        """JR NZ,n specialized for the hot CPU dispatch path."""
        registers = self.registers
        pc = registers['pc']
        sys_interface = self.sys_interface
        direct_rom = self.direct_rom
        if direct_rom is not None and pc < 0x8000:
            i = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
        else:
            i = sys_interface.read_byte(pc)

        pc += 1
        if registers['f'] & FLAG_ZERO:
            registers['pc'] = pc
            registers['m'] = 2
            return

        if i >= 0x80:
            i -= 0x100
        registers['pc'] = (pc + i) & 0xFFFF
        registers['m'] = 3

    def _jr_z_n(self):
        """JR Z,n specialized for the hot CPU dispatch path."""
        registers = self.registers
        pc = registers['pc']
        sys_interface = self.sys_interface
        direct_rom = self.direct_rom
        if direct_rom is not None and pc < 0x8000:
            i = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
        else:
            i = sys_interface.read_byte(pc)

        pc += 1
        if not (registers['f'] & FLAG_ZERO):
            registers['pc'] = pc
            registers['m'] = 2
            return

        if i >= 0x80:
            i -= 0x100
        registers['pc'] = (pc + i) & 0xFFFF
        registers['m'] = 3

    def _djnz_n(self):
        """Decrement B and jump if not zero."""
        self.registers['b'] = (self.registers['b'] - 1) & 0xFF
        if self.registers['b'] != 0:
            n = self.signed8(self.read8(self.registers['pc']))
            self.registers['pc'] = (self.registers['pc'] + n + 1) & 0xFFFF
            self.registers['m'] = 3  # 12 cycles
        else:
            self.registers['pc'] = (self.registers['pc'] + 1) & 0xFFFF
            self.registers['m'] = 2  # 8 cycles

    # Interrupts
    def _di(self):
        """Disable interrupts."""
        self.registers['ime'] = 0
        self.registers['m'] = 1

    def _ei(self):
        """Enable interrupts next cycle."""
        self.enable_interrupts_next_cycle = True
        self.registers['m'] = 1

    def _halt(self):
        """HALT CPU until interrupt occurs."""
        self.halted = True
        self.registers['m'] = 1

    def _reti(self):
        """Return from interrupt, enable interrupts immediately."""
        lo = self.read8(self.registers['sp'])
        hi = self.read8((self.registers['sp'] + 1) & 0xFFFF)
        self.registers['sp'] = (self.registers['sp'] + 2) & 0xFFFF
        self.registers['pc'] = (hi << 8) | lo
        self.registers['ime'] = 1
        self.registers['m'] = 4  # RETI should consume 4 machine cycles

    # PUSH / POP
    def _push_nn(self, r1, r2):
        """Push register pair nn onto stack.

        Decrement Stack Pointer (SP) twice.
        """
        self.registers['sp'] = (self.registers['sp'] - 1) & 0xFFFF
        self.write8(self.registers['sp'], self.registers[r1])
        self.registers['sp'] = (self.registers['sp'] - 1) & 0xFFFF
        self.write8(self.registers['sp'], self.registers[r2])
        self.registers['m'] = 4

    def _pop_nn(self, r1, r2):
        """Pop register pair nn onto stack.

        Increment Stack Pointer (SP) twice.
        """
        lo = self.read8(self.registers['sp'])
        self.registers['sp'] = (self.registers['sp'] + 1) & 0xFFFF
        hi = self.read8(self.registers['sp'])
        self.registers['sp'] = (self.registers['sp'] + 1) & 0xFFFF

        if (r1, r2) == ('a', 'f'):
            lo &= 0xF0  # Only keep upper nibble (Z, N, H, C)
        self.registers[r2] = lo
        self.registers[r1] = hi
        self.registers['m'] = 3

    # CALLs
    def _call_nn(self):
        """Push address of next instr onto stack and then jump to address nn.

        Opcode #205
        """
        target = self.read16(self.registers['pc'])
        # print(f"CALL to {target:04X} from {self.registers['pc']:04X} SP={self.registers['sp']:04X}")
        self.registers['sp'] = (self.registers['sp'] - 2) & 0xFFFF
        self.write16(self.registers['sp'], self.registers['pc'] + 2)
        self.registers['pc'] = target
        self.registers['m'] = 6

    def _call_cc_nn(self, flag_mask, expected_value):
        """Conditionally CALL nn if flag matches."""
        address = self.read16(self.registers['pc'])
        self.registers['pc'] += 2
        self.registers['m'] = 3

        if (self.registers['f'] & flag_mask) == expected_value:
            self.registers['sp'] = (self.registers['sp'] - 2) & 0xFFFF
            self.write16(self.registers['sp'], self.registers['pc'])
            self.registers['pc'] = address
            self.registers['m'] += 3

    # SUB / ADD
    def _sub_n(self, r):
        """Subtract r from A."""
        a = self.registers['a']
        val = self.registers[r]
        result = a - val

        self.registers['f'] = FLAG['sub']  # Always set SUB flag

        if (result & 0xFF) == 0:
            self.registers['f'] |= FLAG['zero']
        if (a & 0xF) < (val & 0xF):
            self.registers['f'] |= FLAG['half-carry']
        if result < 0:
            self.registers['f'] |= FLAG['carry']

        self.registers['a'] = result & 0xFF
        self.registers['m'] = 1

    def _sub_n_imm(self):
        """Subtract immediate 8-bit value from A."""
        value = self.read8(self.registers['pc'])
        self.registers['pc'] += 1

        a = self.registers['a']
        result = a - value

        self.registers['f'] = FLAG['sub']  # always set subtract flag

        if (result & 0xFF) == 0:
            self.registers['f'] |= FLAG['zero']
        if (a & 0xF) < (value & 0xF):
            self.registers['f'] |= FLAG['half-carry']
        if result < 0:
            self.registers['f'] |= FLAG['carry']

        self.registers['a'] = result & 0xFF
        self.registers['m'] = 2

    def _sub_a_n(self, n):
        """Subtract n + Carry flag from A."""
        self.__sbc_from_a(self.registers[n])
        self.registers['m'] = 1

    def _sbc_a_hl(self):
        """Subtract the byte at HL and Carry from A."""
        address = (self.registers['h'] << 8) | self.registers['l']
        self.__sbc_from_a(self.read8(address))
        self.registers['m'] = 2

    def _sbc_n(self):
        """Subtract an immediate byte and Carry from A."""
        value = self.read8(self.registers['pc'])
        self.registers['pc'] = (self.registers['pc'] + 1) & 0xFFFF
        self.__sbc_from_a(value)
        self.registers['m'] = 2

    def __sbc_from_a(self, value):
        """Shared SBC logic with Z, N, H, and C flag updates."""
        a = self.registers['a']
        carry = 1 if self.registers['f'] & FLAG['carry'] else 0
        result = a - value - carry

        self.registers['f'] = FLAG['sub']
        if (result & 0xFF) == 0:
            self.registers['f'] |= FLAG['zero']
        if (a & 0x0F) < ((value & 0x0F) + carry):
            self.registers['f'] |= FLAG['half-carry']
        if a < value + carry:
            self.registers['f'] |= FLAG['carry']

        self.registers['a'] = result & 0xFF

    def _sub_hl(self):
        """Subtract value at HL from A."""
        hl_addr = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(hl_addr)
        a = self.registers['a']

        result = a - value

        self.registers['f'] = FLAG['sub']  # Always set Subtract flag
        if (result & 0xFF) == 0:
            self.registers['f'] |= FLAG['zero']
        if (a & 0xF) < (value & 0xF):
            self.registers['f'] |= FLAG['half-carry']
        if result < 0:
            self.registers['f'] |= FLAG['carry']

        self.registers['a'] = result & 0xFF
        self.registers['m'] = 2


    def _cp_n(self, n):
        """Compare register A with n."""
        registers = self.registers
        if n == 'pc':
            value = self.read8(registers['pc'])
            registers['pc'] += 1
            registers['m'] = 2
        else:
            value = registers[n]
            registers['m'] = 1

        registers['f'] = CP_FLAG_TABLE[(registers['a'] << 8) | value]

    def _cp_b(self):
        """Compare A with B, specialized for opcode 0xB8."""
        registers = self.registers
        registers['f'] = CP_FLAG_TABLE[(registers['a'] << 8) | registers['b']]
        registers['m'] = 1

    def _cp_hl(self):
        """Compare A with the byte at HL."""
        registers = self.registers
        address = (registers['h'] << 8) | registers['l']
        sys_interface = self.sys_interface
        if address == 0xFF44 and not sys_interface.memory.gb_doctor_test_mode:
            value = sys_interface.raw_memory[0xFF44]
        else:
            value = sys_interface.read_byte(address)
        a = registers['a']
        registers['f'] = CP_FLAG_TABLE[(a << 8) | value]
        registers['m'] = 2

    def _add_n(self):
        """Add immediate 8-bit value to A."""
        value = self.read8(self.registers['pc'])
        self.registers['pc'] += 1
        self.__add_to_a(value)
        self.registers['m'] = 2

    def _add_a_n(self, n):
        """Add n to A."""
        value = self.registers[n]
        self.__add_to_a(value)
        self.registers['m'] = 1

    def _add_a_hl(self):
        """Add the byte at HL to A."""
        address = (self.registers['h'] << 8) | self.registers['l']
        self.__add_to_a(self.read8(address))
        self.registers['m'] = 2

    def __add_to_a(self, value):
        """Shared logic for adding value to A with flag updates."""
        result = self.registers['a'] + value
        self.registers['f'] = 0

        if (result & 0xFF) == 0:
            self.registers['f'] |= FLAG['zero']
        if ((self.registers['a'] & 0xF) + (value & 0xF)) > 0xF:
            self.registers['f'] |= FLAG['half-carry']
        if result > 0xFF:
            self.registers['f'] |= FLAG['carry']

        self.registers['a'] = result & 0xFF

    def _add_sp_n(self):
        """Add signed immediate value to SP."""
        n = self.read8(self.registers['pc'])
        self.registers['pc'] += 1

        if n > 127:
            n = n - 256

        old_sp = self.registers['sp']
        result = (self.registers['sp'] + n) & 0xFFFF

        self.registers['f'] = 0

        if ((self.registers['sp'] & 0xF) + (n & 0xF)) > 0xF:
            self.registers['f'] |= FLAG['half-carry']
        if ((self.registers['sp'] & 0xFF) + (n & 0xFF)) > 0xFF:
            self.registers['f'] |= FLAG['carry']

        self.registers['sp'] = result
        self.registers['m'] = 4

        # print(f"ADD SP, n: SP {old_sp:04X} + {n} = {self.registers['sp']:04X}")



    def _add_hl_n(self, r1, r2):
        """Add r16 (r1r2) to HL."""
        hl = (self.registers['h'] << 8) + self.registers['l']
        value = (self.registers[r1] << 8) + self.registers[r2]
        result = hl + value

        # Clear N flag
        self.registers['f'] &= ~(FLAG['sub'])

        # Set H flag if carry from bit 11
        if ((hl & 0x0FFF) + (value & 0x0FFF)) > 0x0FFF:
            self.registers['f'] |= FLAG['half-carry']
        else:
            self.registers['f'] &= ~FLAG['half-carry']

        # Set C flag if carry from bit 15
        if result > 0xFFFF:
            self.registers['f'] |= FLAG['carry']
        else:
            self.registers['f'] &= ~FLAG['carry']

        self.registers['h'] = (result >> 8) & 0xFF
        self.registers['l'] = result & 0xFF
        self.registers['m'] = 2  # Actually should be 2 m-cycles for ADD HL, r16

    def _add_hl_sp(self):
        """Add SP to HL."""
        hl = (self.registers['h'] << 8) + self.registers['l']
        sp = self.registers['sp']
        result = hl + sp

        # Clear N flag
        self.registers['f'] &= ~FLAG['sub']

        # Set H flag if carry from bit 11 (lower 12 bits overflow)
        if ((hl & 0x0FFF) + (sp & 0x0FFF)) > 0x0FFF:
            self.registers['f'] |= FLAG['half-carry']
        else:
            self.registers['f'] &= ~FLAG['half-carry']

        # Set C flag if carry from bit 15 (full 16 bits overflow)
        if result > 0xFFFF:
            self.registers['f'] |= FLAG['carry']
        else:
            self.registers['f'] &= ~FLAG['carry']

        self.registers['h'] = (result >> 8) & 0xFF
        self.registers['l'] = result & 0xFF
        self.registers['m'] = 2

    def _adc_a_n(self, n):
        """Add register n + carry to register A."""
        carry = 1 if (self.registers['f'] & FLAG['carry']) else 0
        value = self.registers[n]
        result = self.registers['a'] + value + carry

        # Set flags
        self.registers['f'] = 0  # Clear flags first
        if result & 0xFF == 0:
            self.registers['f'] |= FLAG['zero']
        if ((self.registers['a'] & 0xF) + (value & 0xF) + carry) > 0xF:
            self.registers['f'] |= FLAG['half-carry']
        if result > 0xFF:
            self.registers['f'] |= FLAG['carry']

        self.registers['a'] = result & 0xFF  # Mask to 8 bits
        self.registers['m'] = 1

    def _adc_n(self):
        """Add immediate 8-bit value + carry to A."""
        carry = 1 if (self.registers['f'] & FLAG['carry']) else 0
        value = self.read8(self.registers['pc'])  # Read immediate byte
        self.registers['pc'] = (self.registers['pc'] + 1) & 0xFFFF

        result = self.registers['a'] + value + carry

        self.registers['f'] = 0
        if (result & 0xFF) == 0:
            self.registers['f'] |= FLAG['zero']
        if ((self.registers['a'] & 0xF) + (value & 0xF) + carry) > 0xF:
            self.registers['f'] |= FLAG['half-carry']
        if result > 0xFF:
            self.registers['f'] |= FLAG['carry']

        self.registers['a'] = result & 0xFF
        self.registers['m'] = 2

    def _adc_hl(self):
        """Add value pointed by HL + carry to A."""
        carry = 1 if (self.registers['f'] & FLAG['carry']) else 0
        hl_addr = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(hl_addr)

        result = self.registers['a'] + value + carry

        self.registers['f'] = 0
        if (result & 0xFF) == 0:
            self.registers['f'] |= FLAG['zero']
        if ((self.registers['a'] & 0xF) + (value & 0xF) + carry) > 0xF:
            self.registers['f'] |= FLAG['half-carry']
        if result > 0xFF:
            self.registers['f'] |= FLAG['carry']

        self.registers['a'] = result & 0xFF
        self.registers['m'] = 2

    # INC / DEC
    def _inc_r_r(self, r1, r2, m=2):
        """Increment registers.

        INC HL, INC DE, INC BC
        """
        self.registers[r2] = (self.registers[r2] + 1) & 255
        if not self.registers[r2]:
            self.registers[r1] = (self.registers[r1] + 1) & 255
        self.registers['m'] = m

    def _inc_hl(self):
        """Increment HL, specialized for opcode 0x23."""
        registers = self.registers
        l = (registers['l'] + 1) & 0xFF
        registers['l'] = l
        if l == 0:
            registers['h'] = (registers['h'] + 1) & 0xFF
        registers['m'] = 2

    def _dec_r_r(self, r1, r2, m=2):
        """Decrement registers.

        DEC HL, DEC DE, DEC BC
        """
        self.registers[r2] = (self.registers[r2] - 1) & 255
        if self.registers[r2] == 0xFF:
            self.registers[r1] = (self.registers[r1] - 1) & 255
        self.registers['m'] = m

    def _dec_bc(self):
        """Decrement BC, specialized for opcode 0x0B."""
        registers = self.registers
        c = (registers['c'] - 1) & 0xFF
        registers['c'] = c
        if c == 0xFF:
            registers['b'] = (registers['b'] - 1) & 0xFF
        registers['m'] = 2

    def _dec_r(self, r):
        """Decrement register with correct flags."""
        registers = self.registers
        val = registers[r]
        result = (val - 1) & 0xFF
        flags = (registers['f'] & FLAG_CARRY) | FLAG['sub']
        if result == 0:
            flags |= FLAG_ZERO
        if (val & 0xF) == 0:
            flags |= FLAG_HALF_CARRY

        registers[r] = result
        registers['f'] = flags
        registers['m'] = 1

    def _dec_a(self):
        """Decrement A with correct flags, specialized for opcode 0x3D."""
        registers = self.registers
        val = registers['a']
        result = (val - 1) & 0xFF
        flags = (registers['f'] & FLAG_CARRY) | FLAG['sub']
        if result == 0:
            flags |= FLAG_ZERO
        if (val & 0xF) == 0:
            flags |= FLAG_HALF_CARRY

        registers['a'] = result
        registers['f'] = flags
        registers['m'] = 1

    def _inc_r(self, r):
        """Increment register with correct flags."""
        val = self.registers[r]
        result = (val + 1) & 0xFF

        self.registers[r] = result

        # Preserve the Carry flag
        carry_flag = self.registers['f'] & FLAG['carry']
        self.registers['f'] = carry_flag  # Start with carry preserved

        if result == 0:
            self.registers['f'] |= FLAG['zero']
        if (val & 0xF) + 1 > 0xF:
            self.registers['f'] |= FLAG['half-carry']
        # N flag cleared (INC never sets subtract flag)

        self.registers['m'] = 1


    def _inc_sp(self):
        """Increment stack pointer."""
        self.registers['sp'] = (self.registers['sp'] + 1) & 65535
        self.registers['m'] = 2

    def _dec_sp(self):
        """Decrement stack pointer."""
        self.registers['sp'] = (self.registers['sp'] - 1) & 65535
        self.registers['m'] = 2

    def _inc_hlm(self):
        """Increment the value at memory[HL]."""
        addr = (self.registers['h'] << 8) | self.registers['l']
        val = self.read8(addr)
        result = (val + 1) & 0xFF

        self.write8(addr, result)
        self.registers['f'] &= FLAG['carry']  # Preserve carry only

        if result == 0:
            self.registers['f'] |= FLAG['zero']
        if (val & 0xF) + 1 > 0xF:
            self.registers['f'] |= FLAG['half-carry']

        self.registers['m'] = 3

    def _dec_hlm(self):
        """Decrement the value at memory[HL]."""
        addr = (self.registers['h'] << 8) | self.registers['l']
        val = self.read8(addr)
        result = (val - 1) & 0xFF

        self.write8(addr, result)
        carry = self.registers['f'] & FLAG['carry']
        self.registers['f'] = carry | FLAG['sub']

        if result == 0:
            self.registers['f'] |= FLAG['zero']
        if (val & 0xF) == 0:
            self.registers['f'] |= FLAG['half-carry']

        self.registers['m'] = 3

    def _swap_n(self, n):
        """Swap upper & lower nibbles of n."""
        tr = self.registers[n]
        result = ((tr & 0xF) << 4) | ((tr & 0xF0) >> 4)
        self.registers[n] = result

        self.registers['f'] = 0
        if result == 0:
            self.registers['f'] |= FLAG['zero']

        self.registers['m'] = 2
        # print(f"SWAP done: A={self.registers['a']:02X}")


    # Boolean logic
    def _and_a(self):
        """AND A with itself; A is unchanged, flags are updated."""
        registers = self.registers
        a = registers['a']
        registers['f'] = FLAG_HALF_CARRY | (FLAG_ZERO if a == 0 else 0)
        registers['m'] = 1

    def _and_b(self):
        """AND A with B, specialized for opcode 0xA0."""
        registers = self.registers
        result = registers['a'] & registers['b']
        registers['a'] = result
        registers['f'] = FLAG_HALF_CARRY | (FLAG_ZERO if result == 0 else 0)
        registers['m'] = 1

    def _and_pc(self):
        """AND immediate byte with A, specialized for opcode 0xE6."""
        registers = self.registers
        pc = registers['pc']
        sys_interface = self.sys_interface
        direct_rom = self.direct_rom
        if direct_rom is not None and pc < 0x8000:
            value = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
        else:
            value = sys_interface.read_byte(pc)

        result = registers['a'] & value
        registers['pc'] = pc + 1
        registers['a'] = result
        registers['f'] = FLAG_HALF_CARRY | (FLAG_ZERO if result == 0 else 0)
        registers['m'] = 2

    def _and_n(self, n):
        """Logically AND n with A, result in A."""
        if n == 'pc':
            registers = self.registers
            pc = registers['pc']
            sys_interface = self.sys_interface
            direct_rom = self.direct_rom
            if direct_rom is not None and pc < 0x8000:
                value = direct_rom[pc] if pc < self.direct_rom_length else 0xFF
            else:
                value = sys_interface.read_byte(pc)
            registers['pc'] = pc + 1
            registers['m'] = 2
        elif n == 'hl':
            value = self.read8((self.registers['h'] << 8) + self.registers['l'])
            self.registers['m'] = 2
        else:
            value = self.registers[n]
            self.registers['m'] = 1

        self.registers['a'] &= value
        self.registers['a'] &= 0xFF

        # Set flags: Z, H=1, N=0, C=0
        self.registers['f'] = FLAG['half-carry']
        if self.registers['a'] == 0:
            self.registers['f'] |= FLAG['zero']

    def _or_n(self, n):
        """Logical OR n with register A, result in A."""
        value = self.registers[n]
        self.registers['a'] |= value
        self.registers['a'] &= 0xFF

        # Set flags: Z if zero, otherwise all flags cleared
        self.registers['f'] = 0
        if self.registers['a'] == 0:
            self.registers['f'] |= FLAG['zero']

        self.registers['m'] = 1

    def _or_c(self):
        """Logical OR C with A, specialized for opcode 0xB1."""
        registers = self.registers
        a = registers['a'] | registers['c']
        registers['a'] = a
        registers['f'] = FLAG_ZERO if a == 0 else 0
        registers['m'] = 1

    def _or_hl(self):
        """Logical OR between A and value at memory[HL]."""
        addr = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(addr)

        self.registers['a'] |= value
        self.registers['a'] &= 0xFF

        # Set flags
        self.registers['f'] = 0
        if self.registers['a'] == 0:
            self.registers['f'] |= FLAG['zero']

        self.registers['m'] = 2

    def _or_n_imm(self):
        """Logical OR immediate byte with register A, result in A."""
        value = self.read8(self.registers['pc'])
        self.registers['pc'] += 1

        self.registers['a'] |= value
        self.registers['a'] &= 0xFF

        self.registers['f'] = 0
        if self.registers['a'] == 0:
            self.registers['f'] |= FLAG['zero']

        self.registers['m'] = 2

    def _xor_n_imm(self):
        """Logical XOR immediate byte with register A, result in A."""
        value = self.read8(self.registers['pc'])
        self.registers['pc'] += 1

        self.registers['a'] ^= value
        self.registers['a'] &= 0xFF

        # Set flags: Z if zero, others cleared
        self.registers['f'] = 0
        if self.registers['a'] == 0:
            self.registers['f'] |= FLAG['zero']

        self.registers['m'] = 2

    def _xor_a_n(self, n):
        """Logical XOR n with register A, result in A."""
        value = self.registers[n]
        self.registers['a'] ^= value
        self.registers['a'] &= 0xFF

        # Set flags: Z if zero, otherwise all flags cleared
        self.registers['f'] = 0
        if self.registers['a'] == 0:
            self.registers['f'] |= FLAG['zero']

        self.registers['m'] = 1

    def _xor_n(self):
        """Logical XOR immediate byte with register A, result in A."""
        value = self.read8(self.registers['pc'])
        self.registers['pc'] += 1

        self.registers['a'] ^= value
        self.registers['a'] &= 0xFF

        # Set flags: Z if zero, otherwise all flags cleared
        self.registers['f'] = 0
        if self.registers['a'] == 0:
            self.registers['f'] |= FLAG['zero']

        self.registers['m'] = 2

    def _xor_hl(self):
        """Logical XOR between A and the value pointed to by HL."""
        hl_addr = (self.registers['h'] << 8) + self.registers['l']
        value = self.read8(hl_addr)

        self.registers['a'] ^= value
        self.registers['a'] &= 0xFF  # Ensure result is 8-bit

        # Update flags
        self.registers['f'] = 0  # Clear all flags first
        if self.registers['a'] == 0:
            self.registers['f'] |= FLAG['zero']

        # N, H, and C are reset (already cleared)
        self.registers['m'] = 2  # 2 machine cycles = 8 clock cycles

    # Returns
    def _ret(self):
        """Pop two bytes from stack & jump to that address."""
        target = self.read16(self.registers['sp'])
        # print(f"RET to {target:04X} from SP={self.registers['sp']:04X}")
        self.registers['pc'] = target
        self.registers['sp'] = (self.registers['sp'] + 2) & 0xFFFF
        self.registers['m'] = 4

    def _rst_n(self, n):
        """Push present address onto stack and jump to address $0000 + n.

        n = n = $00,$08,$10,$18,$20,$28,$30,$38
        """
        self._rsv()
        self.registers['sp'] = (self.registers['sp'] - 2) & 0xFFFF
        self.write16(self.registers['sp'], self.registers['pc'])
        self.registers['pc'] = n
        self.registers['m'] = 4

    def _ret_f(self, and_val, flag_check_value):
        """Return if condition is true."""
        self.registers['m'] = 2
        if (self.registers['f'] & and_val) == flag_check_value:
            self.registers['pc'] = self.read16(self.registers['sp'])
            self.registers['sp'] = (self.registers['sp'] + 2) & 0xFFFF
            self.registers['m'] = 5

    def _rsv(self):
        """Copy some values from registers into rsv."""
        for reg in ['a', 'b', 'c', 'd', 'e', 'f', 'h', 'l']:
            self.rsv[reg] = self.registers[reg]

    def _rrs(self):
        """Copy values from rsv into registers."""
        for reg in ['a', 'b', 'c', 'd', 'e', 'f', 'h', 'l']:
            self.registers[reg] = self.rsv[reg]

    def _rra(self):
        """Rotate A right through carry (RRA)."""
        old_carry = 1 if (self.registers['f'] & FLAG['carry']) else 0
        bit0 = self.registers['a'] & 0x01
        self.registers['a'] = (self.registers['a'] >> 1) | (old_carry << 7)
        self.registers['a'] &= 0xFF

        self.registers['f'] = 0
        if bit0:
            self.registers['f'] |= FLAG['carry']
        self.registers['m'] = 1


    def _rla(self):
        """Rotate A left through carry (RLA)."""
        old_carry = 1 if (self.registers['f'] & FLAG['carry']) else 0
        bit7 = (self.registers['a'] >> 7) & 0x01
        self.registers['a'] = ((self.registers['a'] << 1) & 0xFF) | old_carry

        self.registers['f'] = 0
        if bit7:
            self.registers['f'] |= FLAG['carry']
        self.registers['m'] = 1


    # CB opcodes
    def __set_cb_flags(self, result, carry):
        """Set flags shared by CB-prefixed rotate and shift operations."""
        self.registers['f'] = 0
        if result == 0:
            self.registers['f'] |= FLAG['zero']
        if carry:
            self.registers['f'] |= FLAG['carry']

    def _rlc_hlm(self):
        """Rotate the byte at HL left circularly."""
        address = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(address)
        carry = (value >> 7) & 1
        result = ((value << 1) & 0xFF) | carry
        self.write8(address, result)
        self.__set_cb_flags(result, carry)
        self.registers['m'] = 4

    def _rrc_n(self, r):
        """Rotate register r right circularly."""
        value = self.registers[r]
        carry = value & 1
        result = (value >> 1) | (carry << 7)
        self.registers[r] = result
        self.__set_cb_flags(result, carry)
        self.registers['m'] = 2

    def _rrc_hlm(self):
        """Rotate the byte at HL right circularly."""
        address = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(address)
        carry = value & 1
        result = (value >> 1) | (carry << 7)
        self.write8(address, result)
        self.__set_cb_flags(result, carry)
        self.registers['m'] = 4

    def _rl_n(self, r):
        """Rotate register r left through Carry."""
        value = self.registers[r]
        carry_in = 1 if self.registers['f'] & FLAG['carry'] else 0
        carry_out = (value >> 7) & 1
        result = ((value << 1) & 0xFF) | carry_in
        self.registers[r] = result
        self.__set_cb_flags(result, carry_out)
        self.registers['m'] = 2

    def _rl_hlm(self):
        """Rotate the byte at HL left through Carry."""
        address = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(address)
        carry_in = 1 if self.registers['f'] & FLAG['carry'] else 0
        carry_out = (value >> 7) & 1
        result = ((value << 1) & 0xFF) | carry_in
        self.write8(address, result)
        self.__set_cb_flags(result, carry_out)
        self.registers['m'] = 4

    def _srl_n(self, r):
        """Shift register r right logically (SRL)."""
        val = self.registers[r]
        result = val >> 1

        self.registers[r] = result
        self.__set_cb_flags(result, val & 1)
        self.registers['m'] = 2

    def _srl_hlm(self):
        """Shift the byte at HL right logically."""
        address = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(address)
        result = value >> 1
        self.write8(address, result)
        self.__set_cb_flags(result, value & 1)
        self.registers['m'] = 4

    def _rr_n(self, r):
        """Rotate register r right through carry (RR r)."""
        old_val = self.registers[r]
        old_carry = 1 if (self.registers['f'] & FLAG['carry']) else 0
        new_carry = old_val & 0x01

        result = (old_val >> 1) | (old_carry << 7)
        self.registers[r] = result
        self.__set_cb_flags(result, new_carry)
        self.registers['m'] = 2

    def _rr_hlm(self):
        """Rotate the byte at HL right through Carry."""
        address = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(address)
        carry_in = 1 if self.registers['f'] & FLAG['carry'] else 0
        carry_out = value & 1
        result = (value >> 1) | (carry_in << 7)
        self.write8(address, result)
        self.__set_cb_flags(result, carry_out)
        self.registers['m'] = 4

    def _sla_n(self, r):
        """Shift register r left arithmetically."""
        value = self.registers[r]
        carry = (value >> 7) & 1
        result = (value << 1) & 0xFF
        self.registers[r] = result
        self.__set_cb_flags(result, carry)
        self.registers['m'] = 2

    def _sla_hlm(self):
        """Shift the byte at HL left arithmetically."""
        address = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(address)
        carry = (value >> 7) & 1
        result = (value << 1) & 0xFF
        self.write8(address, result)
        self.__set_cb_flags(result, carry)
        self.registers['m'] = 4

    def _sra_n(self, r):
        """Shift register r right while retaining its sign bit."""
        value = self.registers[r]
        carry = value & 1
        result = (value >> 1) | (value & 0x80)
        self.registers[r] = result
        self.__set_cb_flags(result, carry)
        self.registers['m'] = 2

    def _sra_hlm(self):
        """Shift the byte at HL right while retaining its sign bit."""
        address = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(address)
        carry = value & 1
        result = (value >> 1) | (value & 0x80)
        self.write8(address, result)
        self.__set_cb_flags(result, carry)
        self.registers['m'] = 4

    def _swap_hlm(self):
        """Swap the upper and lower nibbles of the byte at HL."""
        address = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(address)
        result = ((value & 0x0F) << 4) | ((value & 0xF0) >> 4)
        self.write8(address, result)
        self.__set_cb_flags(result, 0)
        self.registers['m'] = 4

    def _res_bit_r(self, bit, reg):
        """Reset bit `bit` in register `reg`."""
        self.registers[reg] &= ~(1 << bit)
        self.registers['m'] = 2

    def _res_bit_hlm(self, bit):
        """Reset bit `bit` at memory[HL]."""
        addr = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(addr)
        value &= ~(1 << bit)
        self.write8(addr, value)
        self.registers['m'] = 4

    def _bit_test_r(self, bit, r):
        """Test bit `bit` in register `r`."""
        value = self.registers[r]
        self.__apply_bit_flags(value, bit)
        self.registers['m'] = 2

    def _bit_test_hlm(self, bit):
        """Test bit `bit` in value at memory[HL]."""
        registers = self.registers
        addr = (registers['h'] << 8) | registers['l']
        if (
            0x8000 <= addr <= 0x9FFF
            or 0xC000 <= addr <= 0xFEFF
            or 0xFF80 <= addr <= 0xFFFE
        ):
            value = self.sys_interface.raw_memory[addr]
        else:
            value = self.read8(addr)
        flags = (registers['f'] & FLAG_CARRY) | FLAG_HALF_CARRY
        if not (value & (1 << bit)):
            flags |= FLAG_ZERO
        registers['f'] = flags
        registers['m'] = 4

    def __apply_bit_flags(self, value, bit):
        """Apply flags for BIT b,r/m."""
        self.registers['f'] &= FLAG['carry']  # preserve carry
        self.registers['f'] |= FLAG['half-carry']
        if not (value & (1 << bit)):
            self.registers['f'] |= FLAG['zero']

    def _set_bit_r(self, bit, r):
        """Set bit `bit` in register `r`."""
        self.registers[r] |= (1 << bit)
        self.registers['m'] = 2

    def _set_bit_hlm(self, bit):
        """Set bit `bit` at memory[HL]."""
        addr = (self.registers['h'] << 8) | self.registers['l']
        value = self.read8(addr)
        value |= (1 << bit)
        self.write8(addr, value)
        self.registers['m'] = 4

    # Misc
    def _daa(self):
        """Decimal adjust accumulator."""
        a = self.registers['a']
        f = self.registers['f']
        n = f & FLAG['sub']
        c = f & FLAG['carry']
        h = f & FLAG['half-carry']
        adjust = 0

        if not n:
            if h or (a & 0x0F) > 9:
                adjust += 0x06
            if c or a > 0x99:
                adjust += 0x60
                f |= FLAG['carry']
        else:
            if h:
                adjust |= 0x06
            if c:
                adjust |= 0x60

        a = (a - adjust) if n else (a + adjust)
        a &= 0xFF

        # Set flags
        f &= FLAG['sub'] | FLAG['carry']  # preserve N and C
        if a == 0:
            f |= FLAG['zero']

        self.registers['a'] = a
        self.registers['f'] = f
        self.registers['m'] = 1

    def _stop(self):
        """Handle STOP, including CGB speed-switch handoff via KEY1."""
        registers = self.registers
        sys_interface = self.sys_interface
        registers['pc'] = (registers['pc'] + 1) & 0xFFFF
        if sys_interface.cgb_mode:
            key1 = sys_interface.raw_memory[0xFF4D]
            if key1 & 0x01:
                next_key1 = (key1 ^ 0x80) & 0xFE
                sys_interface.raw_memory[0xFF4D] = next_key1
                sys_interface.double_speed = bool(next_key1 & 0x80)
            else:
                self.stopped = True
        else:
            self.stopped = True
        self.registers['m'] = 1

    def cpl(self):
        """Complement A register (bit flip)."""
        self.registers['a'] = (~self.registers['a']) & 0xFF
        self.registers['f'] &= FLAG['zero'] | FLAG['carry']
        self.registers['f'] |= FLAG['sub'] | FLAG['half-carry']
        self.registers['m'] = 1

    def _ccf(self):
        """Complement Carry Flag."""
        if self.registers['f'] & 0x10:
            # If carry is set, clear it
            self.registers['f'] &= ~0x10
        else:
            # If carry is clear, set it
            self.registers['f'] |= 0x10

        # CCF clears N and H flags, but preserves Z
        self.registers['f'] &= 0x90  # Only preserve Zero (bit 7) and Carry (bit 4)
        self.registers['m'] = 1

    def _rlc_n(self, n):
        """Rotate n left. Old bit 7 to Carry flag."""
        ci, co = (1, FLAG['carry']) if (self.registers[n] & FLAG['zero']) \
            else (0, 0)
        self.registers[n] = (self.registers[n] << 1) + ci
        self.registers[n] &= 255
        f = 0 if self.registers[n] else FLAG['zero']
        self.registers['f'] = (f & 0xEF) + co
        self.registers['m'] = 2

    def _rlc_a(self):
        """Rotate A left. Old bit 7 to Carry flag."""
        ci, co = (1, FLAG['carry']) if (self.registers['a'] & FLAG['zero']) \
            else (0, 0)
        self.registers['a'] = (self.registers['a'] << 1) + ci
        self.registers['a'] &= 255
        self.registers['f'] = co
        self.registers['m'] = 1

    def _scf(self):
        """Set carry flag."""
        self.registers['f'] &= FLAG['zero']
        self.registers['f'] |= FLAG['carry']
        self.registers['m'] = 1

    def _rrca(self):
        """Rotate A right. Old bit 0 to Carry flag."""
        carry = self.registers['a'] & 0x01
        self.registers['a'] = (self.registers['a'] >> 1) | (carry << 7)
        self.registers['f'] = 0
        if carry:
            self.registers['f'] |= 0x10  # Set carry flag
        self.registers['m'] = 1
