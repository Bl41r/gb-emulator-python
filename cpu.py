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

Terminology
-----------
-   Flag is not affected by this operation.
*   Flag is affected according to result of operation.
b   A bit number in any 8-bit register or memory location.
C   Carry flag.
cc  Flag condition code: C,NC,NZ,Z
d   Any 8-bit destination register or memory location.
dd  Any 16-bit destination register or memory location.
e   8-bit signed 2's complement displacement.
f   8 special call locations in page zero.
H   Half-carry flag.
N   Subtraction flag.
NC  Not carry flag
NZ  Not zero flag.
n   Any 8-bit binary number.
nn  Any 16-bit binary number.
r   Any 8-bit register. (A,B,C,D,E,H, or L)
s   Any 8-bit source register or memory location.
sb  A bit in a specific 8-bit register or memory location.
ss  Any 16-bit source register or memory location.
Z   Zero Flag.
"""

FLAG_BITS = {
    'zero': 0x80,           # Z flag
    'subtraction': 0x40,    # N flag
    'half-carry': 0x20,     # H flag
    'carry': 0x10           # C flag
}


class ExecutionHalted(Exception):
    """Raised when halt trap is issued."""

    pass


class GbZ80Cpu(object):
    """The Z80 CPU class."""

    def __init__(self, memory):
        """Initialize an instance."""
        self.clock = {'m': 0, 't': 0}  # Time clocks: 2 types of clock

        self.memory = memory

        # Register set
        self.registers = {
            # 16-bit registers stored as two 8-bit registers
            # 15..8   7..0
            'a': 1, 'f': 0,
            'b': 0, 'c': 0x13,
            'd': 0, 'e': 216,
            'h': 0, 'l': 0,

            # Interrupts enabled/disabled
            'ime': 0,

            # 16-bit registers (program counter, stack pointer)
            'pc': 0x100, 'sp': 0xFFFE,

            # Clock for last instr
            'm': 0      # cpu cycles/4
        }

        self.opcode_map = {
            # opcode number: func to call, args
            0: (self._nop, []),  # NOP
            1: (self._ld_r1r2_nn, ['b', 'c']),  # LDBCnn
            2: (self._ld_r1r2m_a, ['b', 'c']),  # LDBCmA
            3: (self._inc_r_r, ['b', 'c']),  # INCBC
            4: (self._raise_opcode_unimplemented, []),  # INCr_b
            5: (self._raise_opcode_unimplemented, []),  # DECr_b
            6: (self._ld_rn, ['b']),  # LDrn_b
            7: (self._raise_opcode_unimplemented, []),  # RLCA
            8: (self._ld_nn_sp, []),  # LDnnSP -- double check this one...
            9: (self._raise_opcode_unimplemented, []),  # ADDHLBC
            10: (self._ld_a_r1r2m, ['b', 'c']),  # LDABCm
            11: (self._dec_r_r, ['b', 'c']),  # DECBC
            12: (self._raise_opcode_unimplemented, []),  # INCr_c
            13: (self._raise_opcode_unimplemented, []),  # DECr_c
            14: (self._ld_rn, ['c']),  # LDrn_c
            15: (self._raise_opcode_unimplemented, []),  # RRCA
            16: (self._raise_opcode_unimplemented, []),  # DJNZn
            17: (self._ld_r1r2_nn, ['d', 'e']),  # LDDEnn
            18: (self._ld_r1r2m_a, ['d', 'e']),  # LDDEmA
            19: (self._inc_r_r, ['d', 'e']),  # INCDE
            20: (self._raise_opcode_unimplemented, []),  # INCr_d
            21: (self._raise_opcode_unimplemented, []),  # DECr_d
            22: (self._ld_rn, ['d']),  # LDrn_d
            23: (self._raise_opcode_unimplemented, []),  # RLA
            24: (self._raise_opcode_unimplemented, []),  # JRn
            25: (self._raise_opcode_unimplemented, []),  # ADDHLDE
            26: (self._ld_a_r1r2m, ['d', 'e']),  # LDADEm
            27: (self._dec_r_r, ['d', 'e']),  # DECDE
            28: (self._raise_opcode_unimplemented, []),  # INCr_e
            29: (self._raise_opcode_unimplemented, []),  # DECr_e
            30: (self._ld_rn, ['e']),  # LDrn_e
            31: (self._raise_opcode_unimplemented, []),  # RRA
            32: (self._raise_opcode_unimplemented, []),  # JRNZn
            33: (self._ld_r1r2_nn, ['h', 'l']),  # LDHLnn
            34: (self._ld_hlmi_a, []),  # LDHLIA
            35: (self._inc_r_r, ['h', 'l']),  # INCHL
            36: (self._raise_opcode_unimplemented, []),  # INCr_h
            37: (self._raise_opcode_unimplemented, []),  # DECr_h
            38: (self._ld_rn, ['h']),  # LDrn_h
            39: (self._raise_opcode_unimplemented, []),  # XX
            40: (self._raise_opcode_unimplemented, []),  # JRZn
            41: (self._raise_opcode_unimplemented, []),  # ADDHLHL
            42: (self._ld_a_hl_i, []),  # LDAHLI
            43: (self._dec_r_r, ['h', 'l']),  # DECHL
            44: (self._raise_opcode_unimplemented, []),  # INCr_l
            45: (self._raise_opcode_unimplemented, []),  # DECr_l
            46: (self._ld_rn, ['l']),  # LDrn_l
            47: (self._raise_opcode_unimplemented, []),  # CPL
            48: (self._raise_opcode_unimplemented, []),  # JRNCn
            49: (self._ld_sp_nn, []),  # LD SP nn
            50: (self._ld_hlmd_a, []),  # LDHLDA
            51: (self._inc_sp, []),  # INC SP
            52: (self._raise_opcode_unimplemented, []),  # INCHLm
            53: (self._raise_opcode_unimplemented, []),  # DECHLm
            54: (self._ld_hlm_n, []),  # LDHLmn
            55: (self._raise_opcode_unimplemented, []),  # SCF
            56: (self._raise_opcode_unimplemented, []),  # JRCn
            57: (self._raise_opcode_unimplemented, []),  # ADDHLSP
            58: (self._ld_a_hl_d, []),  # LDAHLD
            59: (self._dec_sp, []),  # DECSP
            60: (self._raise_opcode_unimplemented, []),  # INCr_a
            61: (self._raise_opcode_unimplemented, []),  # DECr_a
            62: (self._ld_rn, ['a']),  # LDrn_a
            63: (self._raise_opcode_unimplemented, []),  # CCF
            64: (self._ld_rr, ['b', 'b']),  # LDrr_bb (nop?)
            65: (self._ld_rr, ['b', 'c']),  # LDrr_bc
            66: (self._ld_rr, ['b', 'd']),  # LDrr_bd
            67: (self._ld_rr, ['b', 'e']),  # LDrr_be
            68: (self._ld_rr, ['b', 'h']),  # LDrr_bh
            69: (self._ld_rr, ['b', 'l']),  # LDrr_bl
            70: (self._ld_r_hlm, ['b']),  # LDrHLm_b
            71: (self._ld_rr, ['b', 'a']),  # LDrr_ba
            72: (self._ld_rr, ['c', 'b']),  # LDrr_cb
            73: (self._ld_rr, ['c', 'c']),  # LDrr_cc (nop?)
            74: (self._ld_rr, ['c', 'd']),  # LDrr_cd
            75: (self._ld_rr, ['c', 'e']),  # LDrr_ce
            76: (self._ld_rr, ['c', 'h']),  # LDrr_ch
            77: (self._ld_rr, ['c', 'l']),  # LDrr_cl
            78: (self._ld_r_hlm, ['c']),  # LDrHLm_c
            79: (self._ld_rr, ['c', 'a']),  # LDrr_ca
            80: (self._ld_rr, ['d', 'b']),  # LDrr_db
            81: (self._ld_rr, ['d', 'c']),  # LDrr_dc
            82: (self._ld_rr, ['d', 'd']),  # LDrr_dd (nop?)
            83: (self._ld_rr, ['d', 'e']),  # LDrr_de
            84: (self._ld_rr, ['d', 'h']),  # LDrr_dh
            85: (self._ld_rr, ['d', 'l']),  # LDrr_dl
            86: (self._ld_r_hlm, ['d']),  # LDrHLm_d
            87: (self._ld_rr, ['d', 'a']),  # LDrr_da
            88: (self._ld_rr, ['e', 'b']),  # LDrr_eb
            89: (self._ld_rr, ['e', 'c']),  # LDrr_ec
            90: (self._ld_rr, ['e', 'd']),  # LDrr_ed
            91: (self._ld_rr, ['e', 'e']),  # LDrr_ee (nop?)
            92: (self._ld_rr, ['e', 'h']),  # LDrr_eh
            93: (self._ld_rr, ['e', 'l']),  # LDrr_el
            94: (self._ld_r_hlm, ['e']),  # LDrHLm_e
            95: (self._ld_rr, ['e', 'a']),  # LDrr_ea
            96: (self._ld_rr, ['h', 'b']),  # LDrr_hb
            97: (self._ld_rr, ['h', 'c']),  # LDrr_hc
            98: (self._ld_rr, ['h', 'd']),  # LDrr_hd
            99: (self._ld_rr, ['h', 'e']),  # LDrr_he
            100: (self._ld_rr, ['h', 'h']),  # LDrr_hh (nop?)
            101: (self._ld_rr, ['h', 'l']),  # LDrr_hl
            102: (self._ld_r_hlm, ['h']),  # LDrHLm_h
            103: (self._ld_rr, ['h', 'a']),  # LDrr_ha
            104: (self._ld_rr, ['l', 'b']),  # LDrr_lb
            105: (self._ld_rr, ['l', 'c']),  # LDrr_lc
            106: (self._ld_rr, ['l', 'd']),  # LDrr_ld
            107: (self._ld_rr, ['l', 'e']),  # LDrr_le
            108: (self._ld_rr, ['l', 'h']),  # LDrr_lh
            109: (self._ld_rr, ['l', 'l']),  # LDrr_ll (nop?)
            110: (self._ld_r_hlm, ['l']),  # LDrHLm_l
            111: (self._ld_rr, ['l', 'a']),  # LDrr_la
            112: (self._ld_hlm_r, ['b']),  # LDHLmr_b
            113: (self._ld_hlm_r, ['c']),  # LDHLmr_c
            114: (self._ld_hlm_r, ['d']),  # LDHLmr_d
            115: (self._ld_hlm_r, ['e']),  # LDHLmr_e
            116: (self._ld_hlm_r, ['h']),  # LDHLmr_h
            117: (self._ld_hlm_r, ['l']),  # LDHLmr_l
            118: (self._raise_opcode_unimplemented, []),  # HALT
            119: (self._ld_hlm_r, ['a']),  # LDHLmr_a
            120: (self._ld_rr, ['a', 'b']),  # LDrr_ab
            121: (self._ld_rr, ['a', 'c']),  # LDrr_ac
            122: (self._ld_rr, ['a', 'd']),  # LDrr_ad
            123: (self._ld_rr, ['a', 'e']),  # LDrr_ae
            124: (self._ld_rr, ['a', 'h']),  # LDrr_ah
            125: (self._ld_rr, ['a', 'l']),  # LDrr_al
            126: (self._ld_r_hlm, ['a']),  # LDrHLm_a
            127: (self._ld_rr, ['a', 'a']),  # LDrr_aa (nop?)
            128: (self._raise_opcode_unimplemented, []),  # ADDr_b
            129: (self._raise_opcode_unimplemented, []),  # ADDr_c
            130: (self._raise_opcode_unimplemented, []),  # ADDr_d
            131: (self._raise_opcode_unimplemented, []),  # ADDr_e
            132: (self._raise_opcode_unimplemented, []),  # ADDr_h
            133: (self._raise_opcode_unimplemented, []),  # ADDr_l
            134: (self._raise_opcode_unimplemented, []),  # ADDHL
            135: (self._raise_opcode_unimplemented, []),  # ADDr_a
            136: (self._raise_opcode_unimplemented, []),  # ADCr_b
            137: (self._raise_opcode_unimplemented, []),  # ADCr_c
            138: (self._raise_opcode_unimplemented, []),  # ADCr_d
            139: (self._raise_opcode_unimplemented, []),  # ADCr_e
            140: (self._raise_opcode_unimplemented, []),  # ADCr_h
            141: (self._raise_opcode_unimplemented, []),  # ADCr_l
            142: (self._raise_opcode_unimplemented, []),  # ADCHL
            143: (self._raise_opcode_unimplemented, []),  # ADCr_a
            144: (self._sub_n, ['b']),  # SUBr_b
            145: (self._sub_n, ['c']),  # SUBr_c
            146: (self._sub_n, ['d']),  # SUBr_d
            147: (self._sub_n, ['e']),  # SUBr_e
            148: (self._sub_n, ['h']),  # SUBr_h
            149: (self._sub_n, ['l']),  # SUBr_l
            150: (self._raise_opcode_unimplemented, []),  # SUBHL
            151: (self._sub_n, ['a']),  # SUBr_a
            152: (self._raise_opcode_unimplemented, []),  # SBCr_b
            153: (self._raise_opcode_unimplemented, []),  # SBCr_c
            154: (self._raise_opcode_unimplemented, []),  # SBCr_d
            155: (self._raise_opcode_unimplemented, []),  # SBCr_e
            156: (self._raise_opcode_unimplemented, []),  # SBCr_h
            157: (self._raise_opcode_unimplemented, []),  # SBCr_l
            158: (self._raise_opcode_unimplemented, []),  # SBCHL
            159: (self._raise_opcode_unimplemented, []),  # SBCr_a
            160: (self._raise_opcode_unimplemented, []),  # ANDr_b
            161: (self._raise_opcode_unimplemented, []),  # ANDr_c
            162: (self._raise_opcode_unimplemented, []),  # ANDr_d
            163: (self._raise_opcode_unimplemented, []),  # ANDr_e
            164: (self._raise_opcode_unimplemented, []),  # ANDr_h
            165: (self._raise_opcode_unimplemented, []),  # ANDr_l
            166: (self._raise_opcode_unimplemented, []),  # ANDHL
            167: (self._raise_opcode_unimplemented, []),  # ANDr_a
            168: (self._raise_opcode_unimplemented, []),  # XORr_b
            169: (self._raise_opcode_unimplemented, []),  # XORr_c
            170: (self._raise_opcode_unimplemented, []),  # XORr_d
            171: (self._raise_opcode_unimplemented, []),  # XORr_e
            172: (self._raise_opcode_unimplemented, []),  # XORr_h
            173: (self._raise_opcode_unimplemented, []),  # XORr_l
            174: (self._raise_opcode_unimplemented, []),  # XORHL
            175: (self._raise_opcode_unimplemented, []),  # XORr_a
            176: (self._raise_opcode_unimplemented, []),  # ORr_b
            177: (self._raise_opcode_unimplemented, []),  # ORr_c
            178: (self._raise_opcode_unimplemented, []),  # ORr_d
            179: (self._raise_opcode_unimplemented, []),  # ORr_e
            180: (self._raise_opcode_unimplemented, []),  # ORr_h
            181: (self._raise_opcode_unimplemented, []),  # ORr_l
            182: (self._raise_opcode_unimplemented, []),  # ORHL
            183: (self._raise_opcode_unimplemented, []),  # ORr_a
            184: (self._raise_opcode_unimplemented, []),  # CPr_b
            185: (self._raise_opcode_unimplemented, []),  # CPr_c
            186: (self._raise_opcode_unimplemented, []),  # CPr_d
            187: (self._raise_opcode_unimplemented, []),  # CPr_e
            188: (self._raise_opcode_unimplemented, []),  # CPr_h
            189: (self._raise_opcode_unimplemented, []),  # CPr_l
            190: (self._raise_opcode_unimplemented, []),  # CPHL
            191: (self._raise_opcode_unimplemented, []),  # CPr_a
            192: (self._raise_opcode_unimplemented, []),  # RETNZ
            193: (self._raise_opcode_unimplemented, []),  # POPBC
            194: (self._raise_opcode_unimplemented, []),  # JPNZnn
            195: (self._jp_nn, []),  # JPnn
            196: (self._raise_opcode_unimplemented, []),  # CALLNZnn
            197: (self._raise_opcode_unimplemented, []),  # PUSHBC
            198: (self._raise_opcode_unimplemented, []),  # ADDn
            199: (self._raise_opcode_unimplemented, []),  # RST00
            200: (self._raise_opcode_unimplemented, []),  # RETZ
            201: (self._raise_opcode_unimplemented, []),  # RET
            202: (self._raise_opcode_unimplemented, []),  # JPZnn
            203: (self._raise_opcode_unimplemented, []),  # MAPcb
            204: (self._raise_opcode_unimplemented, []),  # CALLZnn
            205: (self._call_nn, []),  # CALLnn
            206: (self._raise_opcode_unimplemented, []),  # ADCn
            207: (self._raise_opcode_unimplemented, []),  # RST08
            208: (self._raise_opcode_unimplemented, []),  # RETNC
            209: (self._raise_opcode_unimplemented, []),  # POPDE
            210: (self._raise_opcode_unimplemented, []),  # JPNCnn
            211: (self._raise_opcode_unimplemented, []),  # XX
            212: (self._raise_opcode_unimplemented, []),  # CALLNCnn
            213: (self._raise_opcode_unimplemented, []),  # PUSHDE
            214: (self._raise_opcode_unimplemented, []),  # SUBn
            215: (self._raise_opcode_unimplemented, []),  # RST10
            216: (self._raise_opcode_unimplemented, []),  # RETC
            217: (self._raise_opcode_unimplemented, []),  # RETI
            218: (self._raise_opcode_unimplemented, []),  # JPCnn
            219: (self._raise_opcode_unimplemented, []),  # XX
            220: (self._raise_opcode_unimplemented, []),  # CALLCnn
            221: (self._raise_opcode_unimplemented, []),  # XX
            222: (self._raise_opcode_unimplemented, []),  # SBCn
            223: (self._raise_opcode_unimplemented, []),  # RST18
            224: (self._ldh_n_a, []),  # LDIOnA
            225: (self._raise_opcode_unimplemented, []),  # POPHL
            226: (self._ld_c_a, []),  # LDIOCA
            227: (self._raise_opcode_unimplemented, []),  # XX
            228: (self._raise_opcode_unimplemented, []),  # XX
            229: (self._raise_opcode_unimplemented, []),  # PUSHHL
            230: (self._raise_opcode_unimplemented, []),  # ANDn
            231: (self._raise_opcode_unimplemented, []),  # RST20
            232: (self._raise_opcode_unimplemented, []),  # ADDSPn
            233: (self._raise_opcode_unimplemented, []),  # JPHL
            234: (self._ld_nn_a, []),  # LD nn A
            235: (self._raise_opcode_unimplemented, []),  # XX
            236: (self._raise_opcode_unimplemented, []),  # XX
            237: (self._raise_opcode_unimplemented, []),  # XX
            238: (self._raise_opcode_unimplemented, []),  # ORn
            239: (self._raise_opcode_unimplemented, []),  # RST28
            240: (self._ldh_a_n, []),  # LD AIO n
            241: (self._raise_opcode_unimplemented, []),  # POPAF
            242: (self._ld_a_c, []),  # LDAIOC
            243: (self._di, []),  # DI
            244: (self._raise_opcode_unimplemented, []),  # XX
            245: (self._raise_opcode_unimplemented, []),  # PUSHAF
            246: (self._raise_opcode_unimplemented, []),  # XORn
            247: (self._raise_opcode_unimplemented, []),  # RST30
            248: (self._ld_hl_sp_n, []),  # LD HL SP+n
            249: (self._ld_sp_hl, []),  # LS SP HL
            250: (self._ld_a_nn, []),  # LD A nn
            251: (self._ei, []),  # EI
            252: (self._raise_opcode_unimplemented, []),  # XX
            253: (self._raise_opcode_unimplemented, []),  # XX
            254: (self._raise_opcode_unimplemented, []),  # CPn
            255: (self._raise_opcode_unimplemented, []),  # RST38
        }

    def execute_next_operation(self):
        """Execute the next operation."""
        op = self.read8(self.registers['pc'])
        print('--------------------')
        print("registers before exec:", self.registers)
        self.registers['pc'] += 1
        self.registers['pc'] &= 65535   # mask to 16-bits
        instruction = self.opcode_map[op]
        print("op:", op)
        opcode, args = instruction[0], instruction[1]
        opcode(*args)
        self._inc_clock()
        print("registers after exec:", self.registers)
        import pdb; pdb.set_trace()

    def execute_specific_instruction(self, op):
        """Execute an instruction (for testing)."""
        instruction = self.opcode_map[op]
        print(instruction)
        opcode, args = instruction[0], instruction[1]
        opcode(*args)
        self._inc_clock()

    def reset(self):
        """Reset registers."""
        for k in self.clock.items():
            self.clock[k] = 0
        for k in self.registers.items():
            self.registers[k] = 0

    def read8(self, address):
        """Return a byte from memory at address."""
        return self.memory.read_byte(address)

    def write8(self, address, val):
        """Write a byte to memory at address."""
        self.memory.write_byte(address, val)

    def read16(self, address):
        """Return a word(16-bits) from memory."""
        return self.memory.read_word(address)

    def write16(self, address, val):
        """Write a word to memory at address."""
        self.memory.write_word(address, val)

    def _inc_clock(self):
        """Increment clock registers."""
        self.clock['m'] += self.registers['m']
        self.clock['t'] += self.registers['t']

    def _toggle_flag(self, flag_value):
        self.registers['f'] |= flag_value

    def _raise_opcode_unimplemented(self):
        raise Exception("Opcode unimplemented!")

    # Opcodes
    # ----------------------------
    def _nop(self):
        """NOP opcode."""
        self.registers['m'] = 1
        self.registers['t'] = 4

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
        address = (self.registers['h'] << 8) + self.registers['l']
        self.write8(address, self.registers['pc'])
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
        self.registers[r1] = self.read8(self.registers['pc'])
        self.registers[r2] = self.read8(self.registers['pc'] + 1)
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
        self.registers['a'] = self.read8(0xFF00 + n)
        self.registers['pc'] += 1
        self.registers['m'] = 3

    def _ldh_n_a(self):
        """Put register A into mem @ address $FF00+n."""
        print("sum", 0xFF00 + self.read8(self.registers['pc']))
        n = self.read8(0xFF00 + self.read8(self.registers['pc']))
        self.write8(n, self.registers['a'])
        self.registers['pc'] += 1
        self.registers['m'] = 3

    def _ld_a_c(self):
        """Put value @ address $FF00+C into register A."""
        self.registers['a'] = self.read8(0xFF00 + self.registers['c'])
        self.registers['m'] = 2

    def _ld_c_a(self):
        """Put A into mem @ address $FF00 + C."""
        self.write8(self.read8(0xFF00 + self.registers['c']))
        self.registers['m'] = 2

    def _ld_hl_sp_n(self):
        """Put SP+n effective address into HL.

        n = 1 byte signed immediate value
        """
        n = self.read8(self.registers['pc'])
        if n > 127:
            n = ((~n + 1) & 255)
        result = n + self.registers['sp']

        # set flags
        self.registers['f'] = 0
        xor_result = (self.registers['sp'] ^ n ^ result)
        if (xor_result & 0x100) == 0x100:
            self._toggle_flag(FLAG_BITS['carry'])
        if (xor_result & 0x10) == 0x10:
            self._toggle_flag(FLAG_BITS['half-carry'])

        self.registers['h'] = (result >> 8) & 255
        self.registers['l'] = result & 255
        self.registers['pc'] += 1
        self.registers['m'] = 3

    def _ld_sp_hl(self):
        """Put HL into SP."""
        self.registers['sp'] = (self.registers['h'] << 8) + self.registers['l']
        self.registers['m'] = 2

    # Jumps
    def _jp_nn(self):
        """."""
        self.registers['pc'] = self.read16(self.registers['pc'])
        self.registers['m'] = 3

    # Interrupts
    def _di(self):
        """Disable interrupts."""
        self.registers['ime'] = 0
        self.registers['m'] = 1

    def _ei(self):
        """Enable interrupts."""
        self.registers['ime'] = 1
        self.registers['m'] = 1

    # CALLs
    def _call_nn(self):
        """Push address of next instr onto stack and then jump to address nn.

        Opcode #205
        """
        self.registers['sp'] -= 2
        self.write16(self.registers['sp'], self.registers['pc'] + 2)
        self.registers['pc'] = self.read16(self.registers['pc'])
        self.registers['m'] = 5

    # SUB
    def _sub_n(self, r):
        """Subtract n from A.

        n = A,B,C,D,E,H,L
        """
        a = self.registers['a']
        self.registers['a'] -= self.registers[r]
        self.registers['f'] = 0x50 if self.registers['a'] < 0 else 0x40
        self.registers['a'] &= 255

        if not self.registers['a']:
            self.registers['f'] |= 0x80
        if ((self.registers['a'] ^ self.registers[r] ^ a) & 0x10):
            self.registers['f'] |= 0x20
        self.registers['m'] = 1

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
        if self.registers[r2]:
            self.registers[r1] = (self.registers[r1] - 1) & 255
        self.registers['m'] = m

    def _inc_sp(self):
        """Increment stack pointer."""
        self.registers['sp'] = (self.registers['sp'] + 1) & 65535
        self.registers['m'] = 1

    def _dec_sp(self):
        """Decrement stack pointer."""
        self.registers['sp'] = (self.registers['sp'] - 1) & 65535
        self.registers['m'] = 1



