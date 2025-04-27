"""The CPU.

The CPU in the original GameBoy is a modified Zilog Z80.

http://www.devrs.com/gb/files/opcodes.html :
The GameBoy has instructions & registers similiar to the 8080, 8085, & Z80
microprocessors. The internal 8-bit registers are A, B, C, D, E, F, H, & L.
Theses registers may be used in pairs for 16-bit operations as AF, BC, DE, &
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
import sys


FLAG = {
    'zero': 0x80,           # Z flag
    'sub': 0x40,    # N flag
    'half-carry': 0x20,     # H flag
    'carry': 0x10           # C flag
}

my_counter = 0


class ExecutionHalted(Exception):
    """Raised when execution should stop."""

    pass


class GbZ80Cpu(object):
    """The Z80 CPU class."""

    def __init__(self):
        """Initialize an instance."""
        self.clock = {'m': 0}  # Time clock

        self.sys_interface = None    # Set after interface instantiated.

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
            'pc': 0x100, 'sp': 0xFFFE,

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
            11: (self._dec_r_r, ('b', 'c')),  # DECBC
            12: (self._inc_r, ('c',)),  # INCr_c
            13: (self._dec_r, ('c',)),  # DECr_c
            14: (self._ld_rn, ('c',)),  # LDrn_c
            15: (self._rrca, ()),  # RRCA
            16: (self._djnz_n, ()),  # DJNZn
            17: (self._ld_r1r2_nn, ('d', 'e')),  # LDDEnn
            18: (self._ld_r1r2m_a, ('d', 'e')),  # LDDEmA
            19: (self._inc_r_r, ('d', 'e')),  # INCDE
            20: (self._inc_r, ('d',)),  # INCr_d
            21: (self._dec_r, ('d',)),  # DECr_d
            22: (self._ld_rn, ('d',)),  # LDrn_d
            23: (self._raise_opcode_unimplemented, ()),  # RLA
            24: (self._jr_n, ()),  # JRn
            25: (self._add_hl_n, ('d', 'e')),  # ADDHLDE
            26: (self._ld_a_r1r2m, ('d', 'e')),  # LDADEm
            27: (self._dec_r_r, ('d', 'e')),  # DECDE
            28: (self._inc_r, ('e',)),  # INCr_e
            29: (self._dec_r, ('e',)),  # DECr_e
            30: (self._ld_rn, ('e',)),  # LDrn_e
            31: (self._raise_opcode_unimplemented, ()),  # RRA
            32: (self._jr_cc_n, (FLAG['zero'], 0x00)),  # JRNZn
            33: (self._ld_r1r2_nn, ('h', 'l')),  # LDHLnn
            34: (self._ld_hlmi_a, ()),  # LDHLIA
            35: (self._inc_r_r, ('h', 'l')),  # INCHL
            36: (self._inc_r, ('h',)),  # INCr_h
            37: (self._dec_r, ('h',)),  # DECr_h
            38: (self._ld_rn, ('h',)),  # LDrn_h
            39: (self._nop, ()),  # XX
            40: (self._jr_cc_n, (FLAG['zero'], FLAG['zero'])),  # JRZn
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
            52: (self._raise_opcode_unimplemented, ()),  # INCHLm
            53: (self._raise_opcode_unimplemented, ()),  # DECHLm
            54: (self._ld_hlm_n, ()),  # LDHLmn
            55: (self._scf, ()),  # SCF
            56: (self._jr_cc_n, (0x10, 0x10)),  # JRCn
            57: (self._add_hl_sp, ()),  # ADDHLSP
            58: (self._ld_a_hl_d, ()),  # LDAHLD
            59: (self._dec_sp, ()),  # DECSP
            60: (self._inc_r, ('a',)),  # INCr_a
            61: (self._dec_r, ('a',)),  # DECr_a
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
            120: (self._ld_rr, ('a', 'b')),  # LDrr_ab
            121: (self._ld_rr, ('a', 'c')),  # LDrr_ac
            122: (self._ld_rr, ('a', 'd')),  # LDrr_ad
            123: (self._ld_rr, ('a', 'e')),  # LDrr_ae
            124: (self._ld_rr, ('a', 'h')),  # LDrr_ah
            125: (self._ld_rr, ('a', 'l')),  # LDrr_al
            126: (self._ld_r_hlm, ('a',)),  # LDrHLm_a
            127: (self._ld_rr, ('a', 'a')),  # LDrr_aa (nop?)
            128: (self._add_a_n, ('b',)),  # ADDr_b
            129: (self._add_a_n, ('c',)),  # ADDr_c
            130: (self._add_a_n, ('d',)),  # ADDr_d
            131: (self._add_a_n, ('e',)),  # ADDr_e
            132: (self._add_a_n, ('h',)),  # ADDr_h
            133: (self._add_a_n, ('l',)),  # ADDr_l
            134: (self._raise_opcode_unimplemented, ()),  # ADDHL
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
            158: (self._raise_opcode_unimplemented, ()),  # SBCHL
            159: (self._sub_a_n, ('a',)),  # SBCr_a
            160: (self._and_n, ('b',)),  # ANDr_b
            161: (self._and_n, ('c',)),  # ANDr_c
            162: (self._and_n, ('d',)),  # ANDr_d
            163: (self._and_n, ('e',)),  # ANDr_e
            164: (self._and_n, ('h',)),  # ANDr_h
            165: (self._and_n, ('l',)),  # ANDr_l
            166: (self._and_n, ('hl',)),  # ANDHL
            167: (self._and_n, ('a',)),  # ANDr_a
            168: (self._xor_a_n, ('b',)),  # XORr_b
            169: (self._xor_a_n, ('c',)),  # XORr_c
            170: (self._xor_a_n, ('d',)),  # XORr_d
            171: (self._xor_a_n, ('e',)),  # XORr_e
            172: (self._xor_a_n, ('h',)),  # XORr_h
            173: (self._xor_a_n, ('l',)),  # XORr_l
            174: (self._xor_hl, ()),  # XORHL
            175: (self._xor_a_n, ('a',)),  # XORr_a
            176: (self._or_n, ('b',)),  # ORr_b
            177: (self._or_n, ('c',)),  # ORr_c
            178: (self._or_n, ('d',)),  # ORr_d
            179: (self._or_n, ('e',)),  # ORr_e
            180: (self._or_n, ('h',)),  # ORr_h
            181: (self._or_n, ('l',)),  # ORr_l
            182: (self._raise_opcode_unimplemented, ()),  # ORHL
            183: (self._or_n, ('a',)),  # ORr_a
            184: (self._cp_n, ('b',)),  # CPr_b
            185: (self._cp_n, ('c',)),  # CPr_c
            186: (self._cp_n, ('d',)),  # CPr_d
            187: (self._cp_n, ('e',)),  # CPr_e
            188: (self._cp_n, ('h',)),  # CPr_h
            189: (self._cp_n, ('l',)),  # CPr_l
            190: (self._raise_opcode_unimplemented, ()),  # CPHL
            191: (self._cp_n, ('a',)),  # CPr_a
            192: (self._ret_f, (FLAG['zero'], 0x00)),  # RETNZ
            193: (self._pop_nn, ('b', 'c')),  # POPBC
            194: (self._jp_cc_nn, (FLAG['zero'], 0x00)),  # JPNZnn
            195: (self._jp_nn, ()),  # JPnn
            196: (self._raise_opcode_unimplemented, ()),  # CALLNZnn
            197: (self._push_nn, ('b', 'c')),  # PUSHBC
            198: (self._raise_opcode_unimplemented, ()),  # ADDn
            199: (self._rst_n, (0x00,)),  # RST00
            200: (self._ret_f, (FLAG['zero'], FLAG['zero'])),  # RETZ
            201: (self._ret, ()),  # RET
            202: (self._jp_cc_nn, (FLAG['zero'], FLAG['zero'])),  # JPZnn
            203: (self._call_cb_op, ()),  # MAPcb
            204: (self._raise_opcode_unimplemented, ()),  # CALLZnn
            205: (self._call_nn, ()),  # CALLnn
            206: (self._adc_n, ()),  # ADCn
            207: (self._rst_n, (0x08,)),  # RST08
            208: (self._ret_f, (FLAG['carry'], 0x00)),  # RETNC
            209: (self._pop_nn, ('d', 'e')),  # POPDE
            210: (self._jp_cc_nn, (FLAG['carry'], 0x00)),  # JPNCnn
            211: (self._nop, ()),  # XX
            212: (self._raise_opcode_unimplemented, ()),  # CALLNCnn
            213: (self._push_nn, ('d', 'e')),  # PUSHDE
            214: (self._raise_opcode_unimplemented, ()),  # SUBn
            215: (self._rst_n, (FLAG['carry'],)),  # RST10
            216: (self._ret_f, (FLAG['carry'], FLAG['carry'])),  # RETC
            217: (self._reti, ()),  # RETI
            218: (self._jp_cc_nn, (FLAG['carry'], FLAG['carry'])),  # JPCnn
            219: (self._nop, ()),  # XX
            220: (self._raise_opcode_unimplemented, ()),  # CALLCnn
            221: (self._nop, ()),  # XX
            222: (self._raise_opcode_unimplemented, ()),  # SBCn
            223: (self._rst_n, (0x18,)),  # RST18
            224: (self._ldh_n_a, ()),  # LDIOnA
            225: (self._pop_nn, ('h', 'l')),  # POPHL
            226: (self._ld_c_a, ()),  # LDIOCA
            227: (self._nop, ()),  # XX
            228: (self._nop, ()),  # XX
            229: (self._push_nn, ('h', 'l')),  # PUSHHL
            230: (self._and_n, ('pc',)),  # ANDn
            231: (self._rst_n, (FLAG['half-carry'],)),  # RST20
            232: (self._add_sp_n, ()),  # ADDSPn
            233: (self._raise_opcode_unimplemented, ()),  # JPHL
            234: (self._ld_nn_a, ()),  # LD nn A
            235: (self._nop, ()),  # XX
            236: (self._nop, ()),  # XX
            237: (self._nop, ()),  # XX
            238: (self._raise_opcode_unimplemented, ()),  # ORn
            239: (self._rst_n, (0x28)),  # RST28
            240: (self._ldh_a_n, ()),  # LD AIO n
            241: (self._pop_nn, ('a', 'f')),  # POPAF
            242: (self._ld_a_c, ()),  # LDAIOC
            243: (self._di, ()),  # DI
            244: (self._nop, ()),  # XX
            245: (self._push_nn, ('a', 'f')),  # PUSHAF
            246: (self._xor_n, ()),  # XORn
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
            6: (self._raise_cb_op_unimplemented, ['rlchl']),  # RLCHL
            7: (self._rlc_n, ['a']),  # RLCr_a
            8: (self._raise_cb_op_unimplemented, ['rrcr_b']),  # RRCr_b
            9: (self._raise_cb_op_unimplemented, ['rrcr_c']),  # RRCr_c
            10: (self._raise_cb_op_unimplemented, ['rrcr_d']),  # RRCr_d
            11: (self._raise_cb_op_unimplemented, ['rrcr_e']),  # RRCr_e
            12: (self._raise_cb_op_unimplemented, ['rrcr_h']),  # RRCr_h
            13: (self._raise_cb_op_unimplemented, ['rrcr_l']),  # RRCr_l
            14: (self._raise_cb_op_unimplemented, ['rrchl']),  # RRCHL
            15: (self._raise_cb_op_unimplemented, ['rrcr_a']),  # RRCr_a
            16: (self._raise_cb_op_unimplemented, ['rlr_b']),  # RLr_b
            17: (self._raise_cb_op_unimplemented, ['rlr_c']),  # RLr_c
            18: (self._raise_cb_op_unimplemented, ['rlr_d']),  # RLr_d
            19: (self._raise_cb_op_unimplemented, ['rlr_e']),  # RLr_e
            20: (self._raise_cb_op_unimplemented, ['rlr_h']),  # RLr_h
            21: (self._raise_cb_op_unimplemented, ['rlr_l']),  # RLr_l
            22: (self._raise_cb_op_unimplemented, ['rlhl']),  # RLHL
            23: (self._raise_cb_op_unimplemented, ['rlr_a']),  # RLr_a
            24: (self._raise_cb_op_unimplemented, ['rrr_b']),  # RRr_b
            25: (self._raise_cb_op_unimplemented, ['rrr_c']),  # RRr_c
            26: (self._raise_cb_op_unimplemented, ['rrr_d']),  # RRr_d
            27: (self._raise_cb_op_unimplemented, ['rrr_e']),  # RRr_e
            28: (self._raise_cb_op_unimplemented, ['rrr_h']),  # RRr_h
            29: (self._raise_cb_op_unimplemented, ['rrr_l']),  # RRr_l
            30: (self._raise_cb_op_unimplemented, ['rrhl']),  # RRHL
            31: (self._raise_cb_op_unimplemented, ['rrr_a']),  # RRr_a
            32: (self._raise_cb_op_unimplemented, ['slar_b']),  # SLAr_b
            33: (self._raise_cb_op_unimplemented, ['slar_c']),  # SLAr_c
            34: (self._raise_cb_op_unimplemented, ['slar_d']),  # SLAr_d
            35: (self._raise_cb_op_unimplemented, ['slar_e']),  # SLAr_e
            36: (self._raise_cb_op_unimplemented, ['slar_h']),  # SLAr_h
            37: (self._raise_cb_op_unimplemented, ['slar_l']),  # SLAr_l
            38: (self._raise_cb_op_unimplemented, ['xx']),  # XX
            39: (self._raise_cb_op_unimplemented, ['slar_a']),  # SLAr_a
            40: (self._raise_cb_op_unimplemented, ['srar_b']),  # SRAr_b
            41: (self._raise_cb_op_unimplemented, ['srar_c']),  # SRAr_c
            42: (self._raise_cb_op_unimplemented, ['srar_d']),  # SRAr_d
            43: (self._raise_cb_op_unimplemented, ['srar_e']),  # SRAr_e
            44: (self._raise_cb_op_unimplemented, ['srar_h']),  # SRAr_h
            45: (self._raise_cb_op_unimplemented, ['srar_l']),  # SRAr_l
            46: (self._raise_cb_op_unimplemented, ['xx']),  # XX
            47: (self._raise_cb_op_unimplemented, ['srar_a']),  # SRAr_a
            48: (self._swap_n, ['b']),  # SWAPr_b
            49: (self._swap_n, ['c']),  # SWAPr_c
            50: (self._swap_n, ['d']),  # SWAPr_d
            51: (self._swap_n, ['e']),  # SWAPr_e
            52: (self._swap_n, ['h']),  # SWAPr_h
            53: (self._swap_n, ['l']),  # SWAPr_l
            54: (self._raise_cb_op_unimplemented, ['xx']),  # XX
            55: (self._swap_n, ['a']),  # SWAPr_a
            56: (self._raise_cb_op_unimplemented, ['srlr_b']),  # SRLr_b
            57: (self._raise_cb_op_unimplemented, ['srlr_c']),  # SRLr_c
            58: (self._raise_cb_op_unimplemented, ['srlr_d']),  # SRLr_d
            59: (self._raise_cb_op_unimplemented, ['srlr_e']),  # SRLr_e
            60: (self._raise_cb_op_unimplemented, ['srlr_h']),  # SRLr_h
            61: (self._raise_cb_op_unimplemented, ['srlr_l']),  # SRLr_l
            62: (self._raise_cb_op_unimplemented, ['xx']),  # XX
            63: (self._raise_cb_op_unimplemented, ['srlr_a']),  # SRLr_a
            64: (self._raise_cb_op_unimplemented, ['bit0b']),  # BIT0b
            65: (self._raise_cb_op_unimplemented, ['bit0c']),  # BIT0c
            66: (self._raise_cb_op_unimplemented, ['bit0d']),  # BIT0d
            67: (self._raise_cb_op_unimplemented, ['bit0e']),  # BIT0e
            68: (self._raise_cb_op_unimplemented, ['bit0h']),  # BIT0h
            69: (self._raise_cb_op_unimplemented, ['bit0l']),  # BIT0l
            70: (self._raise_cb_op_unimplemented, ['bit0m']),  # BIT0m
            71: (self._raise_cb_op_unimplemented, ['bit0a']),  # BIT0a
            72: (self._raise_cb_op_unimplemented, ['bit1b']),  # BIT1b
            73: (self._raise_cb_op_unimplemented, ['bit1c']),  # BIT1c
            74: (self._raise_cb_op_unimplemented, ['bit1d']),  # BIT1d
            75: (self._raise_cb_op_unimplemented, ['bit1e']),  # BIT1e
            76: (self._raise_cb_op_unimplemented, ['bit1h']),  # BIT1h
            77: (self._raise_cb_op_unimplemented, ['bit1l']),  # BIT1l
            78: (self._raise_cb_op_unimplemented, ['bit1m']),  # BIT1m
            79: (self._raise_cb_op_unimplemented, ['bit1a']),  # BIT1a
            80: (self._raise_cb_op_unimplemented, ['bit2b']),  # BIT2b
            81: (self._raise_cb_op_unimplemented, ['bit2c']),  # BIT2c
            82: (self._raise_cb_op_unimplemented, ['bit2d']),  # BIT2d
            83: (self._raise_cb_op_unimplemented, ['bit2e']),  # BIT2e
            84: (self._raise_cb_op_unimplemented, ['bit2h']),  # BIT2h
            85: (self._raise_cb_op_unimplemented, ['bit2l']),  # BIT2l
            86: (self._raise_cb_op_unimplemented, ['bit2m']),  # BIT2m
            87: (self._raise_cb_op_unimplemented, ['bit2a']),  # BIT2a
            88: (self._raise_cb_op_unimplemented, ['bit3b']),  # BIT3b
            89: (self._raise_cb_op_unimplemented, ['bit3c']),  # BIT3c
            90: (self._raise_cb_op_unimplemented, ['bit3d']),  # BIT3d
            91: (self._raise_cb_op_unimplemented, ['bit3e']),  # BIT3e
            92: (self._raise_cb_op_unimplemented, ['bit3h']),  # BIT3h
            93: (self._raise_cb_op_unimplemented, ['bit3l']),  # BIT3l
            94: (self._raise_cb_op_unimplemented, ['bit3m']),  # BIT3m
            95: (self._raise_cb_op_unimplemented, ['bit3a']),  # BIT3a
            96: (self._raise_cb_op_unimplemented, ['bit4b']),  # BIT4b
            97: (self._raise_cb_op_unimplemented, ['bit4c']),  # BIT4c
            98: (self._raise_cb_op_unimplemented, ['bit4d']),  # BIT4d
            99: (self._raise_cb_op_unimplemented, ['bit4e']),  # BIT4e
            100: (self._raise_cb_op_unimplemented, ['bit4h']),  # BIT4h
            101: (self._raise_cb_op_unimplemented, ['bit4l']),  # BIT4l
            102: (self._raise_cb_op_unimplemented, ['bit4m']),  # BIT4m
            103: (self._raise_cb_op_unimplemented, ['bit4a']),  # BIT4a
            104: (self._raise_cb_op_unimplemented, ['bit5b']),  # BIT5b
            105: (self._raise_cb_op_unimplemented, ['bit5c']),  # BIT5c
            106: (self._raise_cb_op_unimplemented, ['bit5d']),  # BIT5d
            107: (self._raise_cb_op_unimplemented, ['bit5e']),  # BIT5e
            108: (self._raise_cb_op_unimplemented, ['bit5h']),  # BIT5h
            109: (self._raise_cb_op_unimplemented, ['bit5l']),  # BIT5l
            110: (self._raise_cb_op_unimplemented, ['bit5m']),  # BIT5m
            111: (self._raise_cb_op_unimplemented, ['bit5a']),  # BIT5a
            112: (self._raise_cb_op_unimplemented, ['bit6b']),  # BIT6b
            113: (self._raise_cb_op_unimplemented, ['bit6c']),  # BIT6c
            114: (self._raise_cb_op_unimplemented, ['bit6d']),  # BIT6d
            115: (self._raise_cb_op_unimplemented, ['bit6e']),  # BIT6e
            116: (self._raise_cb_op_unimplemented, ['bit6h']),  # BIT6h
            117: (self._raise_cb_op_unimplemented, ['bit6l']),  # BIT6l
            118: (self._raise_cb_op_unimplemented, ['bit6m']),  # BIT6m
            119: (self._raise_cb_op_unimplemented, ['bit6a']),  # BIT6a
            120: (self._raise_cb_op_unimplemented, ['bit7b']),  # BIT7b
            121: (self._raise_cb_op_unimplemented, ['bit7c']),  # BIT7c
            122: (self._raise_cb_op_unimplemented, ['bit7d']),  # BIT7d
            123: (self._raise_cb_op_unimplemented, ['bit7e']),  # BIT7e
            124: (self._raise_cb_op_unimplemented, ['bit7h']),  # BIT7h
            125: (self._raise_cb_op_unimplemented, ['bit7l']),  # BIT7l
            126: (self._raise_cb_op_unimplemented, ['bit7m']),  # BIT7m
            127: (self._raise_cb_op_unimplemented, ['bit7a']),  # BIT7a
            128: (self._raise_cb_op_unimplemented, ['res0b']),  # RES0b
            129: (self._raise_cb_op_unimplemented, ['res0c']),  # RES0c
            130: (self._raise_cb_op_unimplemented, ['res0d']),  # RES0d
            131: (self._raise_cb_op_unimplemented, ['res0e']),  # RES0e
            132: (self._raise_cb_op_unimplemented, ['res0h']),  # RES0h
            133: (self._raise_cb_op_unimplemented, ['res0l']),  # RES0l
            134: (self._raise_cb_op_unimplemented, ['res0m']),  # RES0m
            135: (self._raise_cb_op_unimplemented, ['res0a']),  # RES0a
            136: (self._raise_cb_op_unimplemented, ['res1b']),  # RES1b
            137: (self._raise_cb_op_unimplemented, ['res1c']),  # RES1c
            138: (self._raise_cb_op_unimplemented, ['res1d']),  # RES1d
            139: (self._raise_cb_op_unimplemented, ['res1e']),  # RES1e
            140: (self._raise_cb_op_unimplemented, ['res1h']),  # RES1h
            141: (self._raise_cb_op_unimplemented, ['res1l']),  # RES1l
            142: (self._raise_cb_op_unimplemented, ['res1m']),  # RES1m
            143: (self._raise_cb_op_unimplemented, ['res1a']),  # RES1a
            144: (self._raise_cb_op_unimplemented, ['res2b']),  # RES2b
            145: (self._raise_cb_op_unimplemented, ['res2c']),  # RES2c
            146: (self._raise_cb_op_unimplemented, ['res2d']),  # RES2d
            147: (self._raise_cb_op_unimplemented, ['res2e']),  # RES2e
            148: (self._raise_cb_op_unimplemented, ['res2h']),  # RES2h
            149: (self._raise_cb_op_unimplemented, ['res2l']),  # RES2l
            150: (self._raise_cb_op_unimplemented, ['res2m']),  # RES2m
            151: (self._raise_cb_op_unimplemented, ['res2a']),  # RES2a
            152: (self._raise_cb_op_unimplemented, ['res3b']),  # RES3b
            153: (self._raise_cb_op_unimplemented, ['res3c']),  # RES3c
            154: (self._raise_cb_op_unimplemented, ['res3d']),  # RES3d
            155: (self._raise_cb_op_unimplemented, ['res3e']),  # RES3e
            156: (self._raise_cb_op_unimplemented, ['res3h']),  # RES3h
            157: (self._raise_cb_op_unimplemented, ['res3l']),  # RES3l
            158: (self._raise_cb_op_unimplemented, ['res3m']),  # RES3m
            159: (self._raise_cb_op_unimplemented, ['res3a']),  # RES3a
            160: (self._raise_cb_op_unimplemented, ['res4b']),  # RES4b
            161: (self._raise_cb_op_unimplemented, ['res4c']),  # RES4c
            162: (self._raise_cb_op_unimplemented, ['res4d']),  # RES4d
            163: (self._raise_cb_op_unimplemented, ['res4e']),  # RES4e
            164: (self._raise_cb_op_unimplemented, ['res4h']),  # RES4h
            165: (self._raise_cb_op_unimplemented, ['res4l']),  # RES4l
            166: (self._raise_cb_op_unimplemented, ['res4m']),  # RES4m
            167: (self._raise_cb_op_unimplemented, ['res4a']),  # RES4a
            168: (self._raise_cb_op_unimplemented, ['res5b']),  # RES5b
            169: (self._raise_cb_op_unimplemented, ['res5c']),  # RES5c
            170: (self._raise_cb_op_unimplemented, ['res5d']),  # RES5d
            171: (self._raise_cb_op_unimplemented, ['res5e']),  # RES5e
            172: (self._raise_cb_op_unimplemented, ['res5h']),  # RES5h
            173: (self._raise_cb_op_unimplemented, ['res5l']),  # RES5l
            174: (self._raise_cb_op_unimplemented, ['res5m']),  # RES5m
            175: (self._raise_cb_op_unimplemented, ['res5a']),  # RES5a
            176: (self._raise_cb_op_unimplemented, ['res6b']),  # RES6b
            177: (self._raise_cb_op_unimplemented, ['res6c']),  # RES6c
            178: (self._raise_cb_op_unimplemented, ['res6d']),  # RES6d
            179: (self._raise_cb_op_unimplemented, ['res6e']),  # RES6e
            180: (self._raise_cb_op_unimplemented, ['res6h']),  # RES6h
            181: (self._raise_cb_op_unimplemented, ['res6l']),  # RES6l
            182: (self._raise_cb_op_unimplemented, ['res6m']),  # RES6m
            183: (self._raise_cb_op_unimplemented, ['res6a']),  # RES6a
            184: (self._raise_cb_op_unimplemented, ['res7b']),  # RES7b
            185: (self._raise_cb_op_unimplemented, ['res7c']),  # RES7c
            186: (self._raise_cb_op_unimplemented, ['res7d']),  # RES7d
            187: (self._raise_cb_op_unimplemented, ['res7e']),  # RES7e
            188: (self._raise_cb_op_unimplemented, ['res7h']),  # RES7h
            189: (self._raise_cb_op_unimplemented, ['res7l']),  # RES7l
            190: (self._raise_cb_op_unimplemented, ['res7m']),  # RES7m
            191: (self._raise_cb_op_unimplemented, ['res7a']),  # RES7a
            192: (self._raise_cb_op_unimplemented, ['set0b']),  # SET0b
            193: (self._raise_cb_op_unimplemented, ['set0c']),  # SET0c
            194: (self._raise_cb_op_unimplemented, ['set0d']),  # SET0d
            195: (self._raise_cb_op_unimplemented, ['set0e']),  # SET0e
            196: (self._raise_cb_op_unimplemented, ['set0h']),  # SET0h
            197: (self._raise_cb_op_unimplemented, ['set0l']),  # SET0l
            198: (self._raise_cb_op_unimplemented, ['set0m']),  # SET0m
            199: (self._raise_cb_op_unimplemented, ['set0a']),  # SET0a
            200: (self._raise_cb_op_unimplemented, ['set1b']),  # SET1b
            201: (self._raise_cb_op_unimplemented, ['set1c']),  # SET1c
            202: (self._raise_cb_op_unimplemented, ['set1d']),  # SET1d
            203: (self._raise_cb_op_unimplemented, ['set1e']),  # SET1e
            204: (self._raise_cb_op_unimplemented, ['set1h']),  # SET1h
            205: (self._raise_cb_op_unimplemented, ['set1l']),  # SET1l
            206: (self._raise_cb_op_unimplemented, ['set1m']),  # SET1m
            207: (self._raise_cb_op_unimplemented, ['set1a']),  # SET1a
            208: (self._raise_cb_op_unimplemented, ['set2b']),  # SET2b
            209: (self._raise_cb_op_unimplemented, ['set2c']),  # SET2c
            210: (self._raise_cb_op_unimplemented, ['set2d']),  # SET2d
            211: (self._raise_cb_op_unimplemented, ['set2e']),  # SET2e
            212: (self._raise_cb_op_unimplemented, ['set2h']),  # SET2h
            213: (self._raise_cb_op_unimplemented, ['set2l']),  # SET2l
            214: (self._raise_cb_op_unimplemented, ['set2m']),  # SET2m
            215: (self._raise_cb_op_unimplemented, ['set2a']),  # SET2a
            216: (self._raise_cb_op_unimplemented, ['set3b']),  # SET3b
            217: (self._raise_cb_op_unimplemented, ['set3c']),  # SET3c
            218: (self._raise_cb_op_unimplemented, ['set3d']),  # SET3d
            219: (self._raise_cb_op_unimplemented, ['set3e']),  # SET3e
            220: (self._raise_cb_op_unimplemented, ['set3h']),  # SET3h
            221: (self._raise_cb_op_unimplemented, ['set3l']),  # SET3l
            222: (self._raise_cb_op_unimplemented, ['set3m']),  # SET3m
            223: (self._raise_cb_op_unimplemented, ['set3a']),  # SET3a
            224: (self._raise_cb_op_unimplemented, ['set4b']),  # SET4b
            225: (self._raise_cb_op_unimplemented, ['set4c']),  # SET4c
            226: (self._raise_cb_op_unimplemented, ['set4d']),  # SET4d
            227: (self._raise_cb_op_unimplemented, ['set4e']),  # SET4e
            228: (self._raise_cb_op_unimplemented, ['set4h']),  # SET4h
            229: (self._raise_cb_op_unimplemented, ['set4l']),  # SET4l
            230: (self._raise_cb_op_unimplemented, ['set4m']),  # SET4m
            231: (self._raise_cb_op_unimplemented, ['set4a']),  # SET4a
            232: (self._raise_cb_op_unimplemented, ['set5b']),  # SET5b
            233: (self._raise_cb_op_unimplemented, ['set5c']),  # SET5c
            234: (self._raise_cb_op_unimplemented, ['set5d']),  # SET5d
            235: (self._raise_cb_op_unimplemented, ['set5e']),  # SET5e
            236: (self._raise_cb_op_unimplemented, ['set5h']),  # SET5h
            237: (self._raise_cb_op_unimplemented, ['set5l']),  # SET5l
            238: (self._raise_cb_op_unimplemented, ['set5m']),  # SET5m
            239: (self._raise_cb_op_unimplemented, ['set5a']),  # SET5a
            240: (self._raise_cb_op_unimplemented, ['set6b']),  # SET6b
            241: (self._raise_cb_op_unimplemented, ['set6c']),  # SET6c
            242: (self._raise_cb_op_unimplemented, ['set6d']),  # SET6d
            243: (self._raise_cb_op_unimplemented, ['set6e']),  # SET6e
            244: (self._raise_cb_op_unimplemented, ['set6h']),  # SET6h
            245: (self._raise_cb_op_unimplemented, ['set6l']),  # SET6l
            246: (self._raise_cb_op_unimplemented, ['set6m']),  # SET6m
            247: (self._raise_cb_op_unimplemented, ['set6a']),  # SET6a
            248: (self._raise_cb_op_unimplemented, ['set7b']),  # SET7b
            249: (self._raise_cb_op_unimplemented, ['set7c']),  # SET7c
            250: (self._raise_cb_op_unimplemented, ['set7d']),  # SET7d
            251: (self._raise_cb_op_unimplemented, ['set7e']),  # SET7e
            252: (self._raise_cb_op_unimplemented, ['set7h']),  # SET7h
            253: (self._raise_cb_op_unimplemented, ['set7l']),  # SET7l
            254: (self._raise_cb_op_unimplemented, ['set7m']),  # SET7m
            255: (self._raise_cb_op_unimplemented, ['set7a']),  # SET7a
        }

    def execute_next_operation(self):
        """Execute the next operation."""
        global my_counter
        my_counter += 1
        op = self.read8(self.registers['pc'])

        # temporary
        print(f"PC={self.registers['pc']:04X} OP={op:02X} SP={self.registers['sp']:04X}")
        if self.registers['pc'] > 0x5E00 and self.read8(self.registers['pc']) == 0x00:
            print(f"!!! Stuck at PC={self.registers['pc']:04X} with NOP (0x00) instruction. Exiting.")
            sys.exit(1)

    # # --- Log for first 1000 instructions ---
        # if my_counter < 1000:
        #     print(f"PC: {hex(self.registers['pc'])}, OP: {hex(op)}, SP: {hex(self.registers['sp'])}")
        # else:
        #     sys.exit(0)
        # # ------------------------------------------------------

        self.registers['pc'] += 1
        self.registers['pc'] &= 65535   # mask to 16-bits
        instruction = self.opcode_map[op]
        opcode, args = instruction[0], instruction[1]

        try:
            # print('executing instr count', my_counter)
            opcode(*args)
            self._inc_clock()
        except Exception as e:
            print("op:", op, 'clock:', self.clock['m'], 'instr_cnt', my_counter)
            raise e

        self.handle_interrupts()  # handle interrupts after each instruction

    def sanity_test_memory_write(self):
        print("Memory at 0xC000 before:", self.sys_interface.read_byte(0xC000))
        self.registers['h'] = 0xC0
        self.registers['l'] = 0x00
        self.registers['a'] = 0x42
        self.write8((self.registers['h'] << 8) | self.registers['l'], self.registers['a'])
        print("Memory at 0xC000 after :", self.sys_interface.read_byte(0xC000))

    def execute_specific_instruction(self, op):
        """Execute an instruction (for testing)."""
        instruction = self.opcode_map[op]
        print(instruction)
        opcode, args = instruction[0], instruction[1]
        opcode(*args)
        self._inc_clock()

    def handle_interrupts(self):
        if not self.registers['ime']:
            return  # interrupts globally disabled

        interrupt_enable = self.sys_interface.read_byte(0xFFFF)
        interrupt_flags = self.sys_interface.read_byte(0xFF0F)
        triggered = interrupt_enable & interrupt_flags
        if triggered:
            for bit, address in enumerate([0x40, 0x48, 0x50, 0x58, 0x60]):
                if triggered & (1 << bit):
                    self._execute_interrupt(bit, address)
                    break  # only handle one interrupt per cycle

    def _execute_interrupt(self, bit, address):
        self.registers['ime'] = 0  # disable further interrupts
        interrupt_flags = self.sys_interface.read_byte(0xFF0F)
        interrupt_flags &= ~(1 << bit)  # clear handled interrupt
        self.sys_interface.write_byte(0xFF0F, interrupt_flags)

        # Push current PC to stack
        self.registers['sp'] -= 2
        self.write16(self.registers['sp'], self.registers['pc'])

        # Jump to interrupt vector
        self.registers['pc'] = address

        # Interrupt takes 5 CPU cycles (20 clock cycles)
        self.registers['m'] = 5

    def reset(self):
        """Reset registers."""
        for k in self.clock.items():
            self.clock[k] = 0
        for k in self.registers.items():
            self.registers[k] = 0

    def read8(self, address):
        """Return a byte from memory at address."""
        return self.sys_interface.read_byte(address)

    def write8(self, address, val):
        """Write a byte to memory at address."""
        self.sys_interface.write_byte(address, val)

    def read16(self, address):
        """Return a word(16-bits) from memory."""
        return self.sys_interface.read_word(address)

    def write16(self, address, val):
        """Write a word to memory at address."""
        self.sys_interface.write_byte(address, val & 0xFF)
        self.sys_interface.write_byte(address + 1, (val >> 8) & 0xFF)

    def _call_cb_op(self):
        """Call an opcode in the cb map."""
        i = self.read8(self.registers['pc'])
        print(f"CB Prefix Opcode {hex(i)} encountered at PC={hex(self.registers['pc'])}")
        self.registers['pc'] += 1
        self.registers['pc'] &= 65535
        op, args = self.cb_map[i]
        op(*args)

    def _inc_clock(self):
        """Increment clock registers and step GPU."""
        self.clock['m'] += self.registers['m']
        if self.sys_interface and self.sys_interface.gpu:
            self.sys_interface.gpu.step(self.registers['m'] * 4)  # 1 m = 4 cycles

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

    def _halt(self):
        """HALT CPU until interrupt."""
        print('halt called')
        self.registers['m'] = 1

    # Loads
    def _ld_rr(self, r1, r2):
        """Load value r2 into r1."""
        self.registers[r1] = self.registers[r2]
        self.registers['m'] = 1

    def _ld_rn(self, r):
        """Load mem @ pc into register r."""
        self.registers[r] = self.read8(self.registers['pc'])
        self.registers['pc'] += 1
        self.registers['m'] = 2

    def _ld_r_hlm(self, r):
        """Load mem @ HL into registers[r]."""
        read_val = self.read8((self.registers['h'] << 8) + self.registers['l'])
        self.registers[r] = read_val
        self.registers['m'] = 2

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

    def _ld_nn_a(self):
        """Load byte registers['a'] into mem @ 16-bit address.

        address = mem (16-bit) @ registers[pc]
        """
        address = self.read16(self.registers['pc'])
        self.write8(address, self.registers['a'])
        self.registers['pc'] += 2
        self.registers['m'] = 4

    def _ld_a_r1r2m(self, r1, r2):
        """Load mem @ r1r2 into registers[a]."""
        address = (self.registers[r1] << 8) + self.registers[r2]
        self.registers['a'] = self.read8(address)
        self.registers['m'] = 2

    def _ld_a_nn(self):
        """Load byte @ address into registers[a].

        address = mem (16-bit) @ registers[pc]
        """
        address = self.read16(self.registers['pc'])
        self.registers['a'] = self.read8(address)
        self.registers['pc'] += 2
        self.registers['m'] = 4

    def _ld_r1r2_nn(self, r1, r2):
        """Load 16-bit immediate value into two 8-bit registers."""
        self.registers[r2] = self.read8(self.registers['pc'])
        self.registers[r1] = self.read8(self.registers['pc'] + 1)
        self.registers['pc'] += 2
        self.registers['m'] = 3

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
        self.registers['m'] = 4

    def _ld_hlmi_a(self):
        """Put A into memory address HL. Increment HL.

        Same as: LD (HL),A - INC HL
        """
        address = (self.registers['h'] << 8) + self.registers['l']
        self.write8(address, self.registers['a'])
        self._inc_r_r('h', 'l', m=2)

    def _ld_hlmd_a(self):
        """Put A into memory address HL. Decrement HL.

        Same as: LD (HL),A - DEC HL
        """
        address = (self.registers['h'] << 8) + self.registers['l']
        self.write8(address, self.registers['a'])
        self._dec_r_r('h', 'l', m=2)

    def _ld_a_hl_i(self):
        """Load mem @ hl into reg a and increment."""
        address = (self.registers['h'] << 8) + self.registers['l']
        self.registers['a'] = self.read8(address)
        self._inc_r_r('h', 'l', m=2)

    def _ld_a_hl_d(self):
        """Load mem @ hl into reg a and decrement."""
        address = (self.registers['h'] << 8) + self.registers['l']
        self.registers['a'] = self.read8(address)
        self._dec_r_r('h', 'l', m=2)

    def _ldh_a_n(self):
        """Put mem @ address $FF00+n into register a."""
        n = self.read8(self.registers['pc'])
        addr = 0xFF00 + n
        val = self.read8(addr)
        self.registers['a'] = val
        self.registers['pc'] += 1
        self.registers['m'] = 3

    def _ldh_n_a(self):
        """Put register A into mem @ address $FF00+n."""
        n = self.read8(self.registers['pc'])
        self.write8(0xFF00 + n, self.registers['a'])
        self.registers['pc'] += 1
        self.registers['m'] = 3

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
        self.registers['m'] = 3

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

    def _jr_n(self):
        """Add signed immediate value to current address and jump to it."""
        i = self.read8(self.registers['pc'])
        i = i if i < 128 else i - 256
        self.registers['pc'] += 1
        self.registers['m'] = 2
        self.registers['pc'] += i
        self.registers['m'] += 1

    def _jr_cc_n(self, and_val, flag_check_value):
        """If Z flag reset, add n to current address and jump to it.

        n = one byte signed immediate value
        """
        i = self.read8(self.registers['pc'])
        if i > 127:
            i = -(~i + 1) & 255
        self.registers['pc'] += 1
        self.registers['m'] = 2
        if (self.registers['f'] & and_val) == flag_check_value:
            self.registers['pc'] += i
            self.registers['m'] += 1

    def _djnz_n(self):
        """Decrement B and jump if not zero."""
        self.registers['b'] = (self.registers['b'] - 1) & 0xFF
        if self.registers['b'] != 0:
            n = self.read8(self.registers['pc'])
            if n > 127:
                n = -((~n + 1) & 0xFF)
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
        """Enable interrupts."""
        self.registers['ime'] = 1
        self.registers['m'] = 1

    # PUSH / POP
    def _push_nn(self, r1, r2):
        """Push register pair nn onto stack.

        Decrement Stack Pointer (SP) twice.
        """
        self.registers['sp'] -= 1
        self.write8(self.registers['sp'], self.registers[r1])
        self.registers['sp'] -= 1
        self.write8(self.registers['sp'], self.registers[r2])
        self.registers['m'] = 3

    def _pop_nn(self, r1, r2):
        """Pop register pair nn onto stack.

        Increment Stack Pointer (SP) twice.
        """
        self.registers[r2] = self.read8(self.registers['sp'])
        self.registers['sp'] += 1
        self.registers[r1] = self.read8(self.registers['sp'])
        self.registers['sp'] += 1
        self.registers['m'] = 3

    # CALLs
    def _call_nn(self):
        """Push address of next instr onto stack and then jump to address nn.

        Opcode #205
        """
        self.registers['sp'] -= 2
        self.write16(self.registers['sp'], self.registers['pc'] + 2)
        self.registers['pc'] = self.read16(self.registers['pc'])
        self.registers['m'] = 5

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

    def _sub_a_n(self, n):
        """Subtract n + Carry flag from A."""
        a = self.registers['a']
        self.registers['a'] -= self.registers[n]
        self.registers['a'] -= 1 \
            if (self.registers['f'] & FLAG['carry']) else 0

        self.registers['f'] = 0x50 if self.registers['a'] < 0 else FLAG['sub']
        self.registers['a'] &= 255
    
        if not self.registers['a']:
            self.registers['f'] |= FLAG['zero']
        if (self.registers['a'] ^ self.registers[n] ^ a) & FLAG['carry']:
            self.registers['f'] |= FLAG['half-carry']
        self.registers['m'] = 1

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
        if n == 'pc':
            value = self.read8(self.registers['pc'])
            self.registers['pc'] += 1
        else:
            value = self.registers[n]

        result = self.registers['a'] - value
        self.registers['f'] = FLAG['sub']

        if (result & 0xFF) == 0:
            self.registers['f'] |= FLAG['zero']
        if (self.registers['a'] & 0xF) < (value & 0xF):
            self.registers['f'] |= FLAG['half-carry']
        if result < 0:
            self.registers['f'] |= FLAG['carry']

        self.registers['m'] = 2


    def _add_a_n(self, n):
        """Add n to A."""
        value = self.registers[n]
        result = self.registers['a'] + value

        self.registers['f'] = 0
        if (result & 0xFF) == 0:
            self.registers['f'] |= FLAG['zero']
        if ((self.registers['a'] & 0xF) + (value & 0xF)) > 0xF:
            self.registers['f'] |= FLAG['half-carry']
        if result > 0xFF:
            self.registers['f'] |= FLAG['carry']

        self.registers['a'] = result & 0xFF
        self.registers['m'] = 1

    def _add_sp_n(self):
        """Add signed immediate value to SP."""
        n = self.read8(self.registers['pc'])
        self.registers['pc'] += 1

        if n > 127:
            n = n - 256

        result = (self.registers['sp'] + n) & 0xFFFF

        # Clear Z and N
        self.registers['f'] = 0

        # Set flags
        if ((self.registers['sp'] & 0xF) + (n & 0xF)) > 0xF:
            self.registers['f'] |= FLAG['half-carry']
        if ((self.registers['sp'] & 0xFF) + (n & 0xFF)) > 0xFF:
            self.registers['f'] |= FLAG['carry']

        self.registers['sp'] = result
        self.registers['m'] = 4


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
            self

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
    def _inc_r_r(self, r1, r2, m=1):
        """Increment registers.

        INC HL, INC DE, INC BC
        """
        self.registers[r2] = (self.registers[r2] + 1) & 255
        if not self.registers[r2]:
            self.registers[r1] = (self.registers[r1] + 1) & 255
        self.registers['m'] = m

    def _dec_r_r(self, r1, r2, m=1):
        """Decrement registers.

        DEC HL, DEC DE, DEC BC
        """
        self.registers[r2] = (self.registers[r2] - 1) & 255
        if self.registers[r2] == 0xFF:
            self.registers[r1] = (self.registers[r1] - 1) & 255
        self.registers['m'] = m

    def _dec_r(self, r):
        """Decrement register r."""
        old_value = self.registers[r]
        self.registers[r] = (self.registers[r] - 1) & 0xFF

        self.registers['f'] = FLAG['sub']
        if self.registers[r] == 0:
            self.registers['f'] |= FLAG['zero']
        if (old_value & 0xF) == 0:
            self.registers['f'] |= FLAG['half-carry']

        self.registers['m'] = 1

    def _inc_r(self, r):
        """Increment register r."""
        old_value = self.registers[r]
        self.registers[r] = (self.registers[r] + 1) & 0xFF

        self.registers['f'] = 0  # N cleared
        if self.registers[r] == 0:
            self.registers['f'] |= FLAG['zero']
        if (old_value & 0xF) == 0xF:
            self.registers['f'] |= FLAG['half-carry']

        self.registers['m'] = 1

    def _inc_sp(self):
        """Increment stack pointer."""
        self.registers['sp'] = (self.registers['sp'] + 1) & 65535
        self.registers['m'] = 1

    def _dec_sp(self):
        """Decrement stack pointer."""
        self.registers['sp'] = (self.registers['sp'] - 1) & 65535
        self.registers['m'] = 1

    def _swap_n(self, n):
        """Swap upper & lower nibbles of n."""
        tr = self.registers[n]
        result = ((tr & 0xF) << 4) | ((tr & 0xF0) >> 4)
        self.registers[n] = result

        self.registers['f'] = 0
        if result == 0:
            self.registers['f'] |= FLAG['zero']

        self.registers['m'] = 2
        print(f"SWAP done: A={self.registers['a']:02X}")


    # Boolean logic
    def _and_n(self, n):
        """Logically AND n with A, result in A."""
        if n == 'pc':
            value = self.read8(self.registers['pc'])
            self.registers['pc'] += 1
            self.registers['m'] = 2
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
        self.registers['pc'] = self.read16(self.registers['sp'])
        self.registers['sp'] += 2
        self.registers['m'] = 3

    def _rst_n(self, n):
        """Push present address onto stack and jump to address $0000 + n.

        n = n = $00,$08,$10,$18,$20,$28,$30,$38
        """
        self._rsv()
        self.registers['sp'] -= 2
        self.write16(self.registers['sp'], self.registers['pc'])
        self.registers['pc'] = n
        self.registers['m'] = 3

    def _reti(self):
        """Pop two bytes from stack & jump to that address.

        Also enable interrupts
        """
        self.registers['ime'] = 1
        self._rrs()
        self.registers['pc'] = self.read16(self.registers['sp'])
        self.registers['sp'] += 2
        self.registers['m'] = 3

    def _ret_f(self, and_val, flag_check_value):
        """Return if condition is true."""
        self.registers['m'] = 1
        if (self.registers['f'] & and_val) == flag_check_value:
            self.registers['pc'] = self.read16(self.registers['sp'])
            self.registers['sp'] += 2
            self.registers['m'] += 2

    def _rsv(self):
        """Copy some values from registers into rsv."""
        for reg in ['a', 'b', 'c', 'd', 'e', 'f', 'h', 'l']:
            self.rsv[reg] = self.registers[reg]

    def _rrs(self):
        """Copy values from rsv into registers."""
        for reg in ['a', 'b', 'c', 'd', 'e', 'f', 'h', 'l']:
            self.registers[reg] = self.rsv[reg]

    # Misc
    def cpl(self):
        """Complement A register (bit flip)."""
        self.registers['a'] = (~self.registers['a']) & 0xFF
        self.registers['f'] &= FLAG['zero']
        self.registers['f'] |= 0x60
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
        self.registers['f'] = (self.registers['f'] & 0xEF) + co
        self.registers['m'] = 1

    def _scf(self):
        """Set carry flag."""
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









