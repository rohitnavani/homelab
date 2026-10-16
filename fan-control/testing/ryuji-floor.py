#!/usr/bin/env python3
# ryuji-floor (2026-10-08): ryuji-profile with plan 'floor': BMC offsets BELOW -80 (the BMC page accepts -1..-127 for
# decreasing) at idle, 4 busy threads and full load, against -80, plus -16 and 0 at idle for the noise table. Goal:
# quieter CPU fans under light load without the new CPUs. Extra safety for the low offsets: every fan (CPU0/1_FAN,
# SYS_FAN1-4; BMC thresholds 800 warning / 600 critical) must stay at FAN_FLOOR rpm or more: the first 60 s after an
# offset change are watched every 5 s, then every 30 s; below the floor the offset goes straight back to -80 and every
# later phase below -80 is skipped. -127 is skipped if -80 and -100 at idle project a fan under the floor there.
# The BMC event log is read before and after (read-only) and new entries are noted. Room gates 26/27C (Rohit 10-07).
# ryuji-profile: thermal profile of ryuji vs BMC fan offset and CPU load. Reusable: rerun after the CPU upgrade
# with a new label and compare (analyze with scripts/analyze_ryuji_profile.py; room temp comes from makoto's
# data/room.csv, joined on the epoch column).
#   Guard stopped; for each BMC fan offset in OFFS: idle, then busy threads (stress-ng matrixprod at 100%) per LOADS;
#   then -80 idle as a drift bracket, then ryuji-fan-guard takes over again. Load steps are gated on the room (ROOM_*).
#   (07:19 and 07:30 runs on 2026-10-06 used guard / -61 / -31 / Performance blocks; replaced after the guard tripped
#   to Performance at the first load step, see STATUS-LOG.)
# Safety: load stops for the rest of a phase at SIO1 >= 80, CPU >= 82, VR >= 95, DIMM >= 80. At SIO1 >= 83 or
# CPU >= 86 the test sets Full Speed (127) and exits; the guard then holds Full until things cool. Any BMC set
# failure exits (no retries). ExecStopPost (ryuji-profile-restore.sh) kills any load and starts ryuji-fan-guard,
# which puts -80 back by itself from any non-guard offset on its first check.
# Run as root on ryuji:
#   systemd-run --unit=ryuji-profile -p ExecStopPost=/var/tmp/ryuji-profile-restore.sh python3 /var/tmp/ryuji-profile.py <label> [plan]
import glob, os, re, subprocess, sys, time

LABEL = sys.argv[1] if len(sys.argv) > 1 else 'run'
CSV = f'/var/tmp/ryuji-profile-{LABEL}.csv'
OFFSET_TOOL = ['python3', '/var/tmp/gbt-fan-offset.py', '10.0.0.118']
ENV = dict(os.environ, BMC_PWFILE='/root/.bmc-pass', BMC_USER='root')
G = None  # guard in control
# Load = number of stress-ng workers at 100% (threads busy; ryuji has 40). A few busy threads is the realistic light
# load (a small VM); duty-cycling all 40 threads keeps every core awake (40 x 10% already draws ~80 W package).
# Offsets: the BMC adds this PWM offset to its own fan curves (UI range -127..127; presets Full 127, Performance 0,
# Balance -31, Energy Saving -61). Measured: -80..-31 leave the system fans at their ~1,050 rpm floor and only move
# the CPU fans; 0 gives 4,000-5,000 rpm system fans. SIO Temp 1 follows system-fan airflow within minutes.
# This sweep maps the in-between offsets (system fans between floor and Performance), loudest first.
# Plans (pick with the 2nd argument; default "full"). Load = busy threads at 100%; FULL = one per physical core (20 on
# 2x E5-2650 v3; 44 after the E5-2696 v4 upgrade). Hyperthreads add nothing with matrixprod (measured 10-06).
#   full:     every offset (loudest first) x idle 10 min / 4 threads 6 min / FULL 6 min, then -80 idle bracket.
#   rest0806: what was left on 10-06 after sweeps 1-2 (offset 0 all loads and -24 idle/4 done earlier).
# 10-06 history: sweep 1 (07:45) cut at 08:11 by the room rule (27C then); sweep 2 (08:25) light loads only;
# 08:4x Rohit allowed a hotter room ("test harder ... leave time for it to cool off"), so full-load steps are back.
FULL = len({tuple(l.split(',')) for l in subprocess.run(['lscpu', '-p=CORE,SOCKET'], capture_output=True, text=True)
            .stdout.splitlines() if not l.startswith('#')}) or 20   # physical cores
STEPS = [(0, 10), (4, 6), (FULL, 6)]
LOW = 'LOW'   # resolved at run time: the lowest offset (-127, then -100) that has not hit the fan floor


def seq(steps):
    """2026-10-13: a designed burst sequence [(workers, minutes)] as guard-controlled phases (hunting check)"""
    return [(f'b{i:02d}_{w}t', None, w, m) for i, (w, m) in enumerate(steps)]


BURST_MED = [(11, 2), (0, 1.5), (4, 3), (11, 1), (0, 0.5), (2, 4), (11, 5), (0, 2), (4, 1.5), (11, 3), (0, 3), (2, 1.5),
             (11, 2)]
BURST_ALL = [(44, 1.5), (0, 2), (22, 3), (4, 2), (33, 1), (0, 1), (44, 4), (11, 2), (0, 3), (33, 2), (2, 1.5),
             (44, 0.5), (0, 1.5), (22, 5)]


PLANS = {
    'floor': [('o-80_0t', -80, 0, 8), ('o-100_0t', -100, 0, 10), ('o-127_0t', -127, 0, 10), ('o-80_0t_b', -80, 0, 6),
              ('o-80_4t', -80, 4, 6), ('o-100_4t', -100, 4, 6), ('o-127_4t', -127, 4, 6), ('o-80_4t_b', -80, 4, 4),
              ('oLOW_full', LOW, FULL, 6), ('o-80_full', -80, FULL, 6),
              ('o-16_0t', -16, 0, 6), ('o0_0t', 0, 0, 6), ('R80_idle', -80, 0, 8)],
    # 2026-10-07 19:30, Rohit winding down for bed: idle and 4 threads only (no full load, no -16/0), quietest first,
    # under noise-guard-ryuji (+3 dB(A) at the mic -> load killed, then the test stopped)
    'night': [('o-80_0t', -80, 0, 6), ('o-100_0t', -100, 0, 10), ('o-127_0t', -127, 0, 10), ('o-80_0t_b', -80, 0, 6),
              ('o-127_4t', -127, 4, 6), ('o-100_4t', -100, 4, 6), ('o-80_4t', -80, 4, 4), ('R80_idle', -80, 0, 8)],
    # 2026-10-08 daytime (the idle offsets were measured the evening before): the loads, -80 brackets, -16 and 0 idle
    'day': [('o-80_0t', -80, 0, 5), ('o-80_4t', -80, 4, 6), ('o-100_4t', -100, 4, 6), ('o-127_4t', -127, 4, 6),
            ('o-80_4t_b', -80, 4, 4), ('o-80_0t_c', -80, 0, 4), ('oLOW_full', LOW, FULL, 6), ('o-80_full', -80, FULL, 6),
            ('o-16_0t', -16, 0, 6), ('o0_0t', 0, 0, 6), ('R80_idle', -80, 0, 8)],
    # 2026-10-08 12:0x: -100 vs -80 under 4 threads again, alternating (A/B/A/B) with the idle right after each load
    # (the day plan: -100 ~0.3 dB quieter but without the ~700 Hz tone; the post-load idle at 2,600 rpm rang it)
    'ab': [('a1_4t', -80, 4, 5), ('a1_idle', -80, 0, 4), ('b1_4t', -100, 4, 5), ('b1_idle', -100, 0, 4),
           ('a2_4t', -80, 4, 5), ('a2_idle', -80, 0, 4), ('b2_4t', -100, 4, 5), ('b2_idle', -100, 0, 4),
           ('R80_idle', -80, 0, 6)],
    # 2026-10-08 18:1x (Rohit away until ~20:30): map ryuji's CPU-fan rpm against the ~700 Hz ringing. Idle: every
    # offset from -127 up to 0 and back down (2 min each); then 4 threads from -127 to 0 and back (2.5 min each).
    'follow': ([(f'i{o}_up', o, 0, 2) for o in (-127, -110, -100, -90, -80, -70, -60, -50, -40, -30, -20, -10, 0)]
               + [(f'i{o}_dn', o, 0, 2) for o in (-10, -20, -30, -40, -50, -60, -70, -80, -90, -100, -110, -127)]
               + [(f't{o}_up', o, 4, 2.5) for o in (-127, -100, -80, -60, -40, -20, 0)]
               + [(f't{o}_dn', o, 4, 2.5) for o in (-20, -40, -60, -80, -100, -127)]
               + [('R80_idle', -80, 0, 4)]),
    # guard in control (offset None): its live validation under light and full load, and the unwind afterwards
    'guardval': [('g_idle', None, 0, 5), ('g_4t', None, 4, 10), ('g_full', None, FULL, 10), ('g_unwind', None, 0, 20)],
    # 2026-10-10 (Rohit home, medium noise allowed 12:00-22:00): does more chassis airflow keep ryuji's PSU fan out of
    # the ~670-790 Hz ringing band under a steady light load? 10-08's 2.5 min holds could not say (the PSU's tone
    # climbs for ~25 min at a constant load). 30 min holds at 4 threads with the system fans at their floor (-80) or
    # lifted (-40: ~1,800-2,200 rpm under load on 10-08), A/B/B/A, each followed by 15 min idle at -80.
    'psu': [('i80_ref', -80, 0, 10), ('a1_4t', -80, 4, 30), ('a1_cool', -80, 0, 15), ('b1_4t', -40, 4, 30),
            ('b1_cool', -80, 0, 15), ('b2_4t', -40, 4, 30), ('b2_cool', -80, 0, 15), ('a2_4t', -80, 4, 30),
            ('R80_idle', -80, 0, 15)],
    # 2026-10-12 evening, first run on the E5-2696 v4s (Rohit home, light testing allowed): guard in control. Does
    # v2.3's -40 step still fire on the new CPUs (METHODOLOGY step 7: it needs the hottest CPU >= 52C), and what do
    # 4 and 8 busy threads cost? Then a long idle tail under the guard = the new idle baseline (step 2).
    'v4light': [('g_warm', None, 0, 45), ('g_ref', None, 0, 10), ('g_4t', None, 4, 30), ('g_unwind4', None, 0, 20),
                ('g_8t', None, 8, 20), ('g_unwind8', None, 0, 25)],
    # 20:0x: at 4 threads the BMC lifts the system fans itself (1,050 -> 1,625 rpm at -80), SIO1 falls, so v2.3's -40
    # step never fires, yet the PSU tone climbed into the ringing band (715 Hz in 5 min). Does -40 still keep it out?
    # B after the guard's -80 g_4t (A), then the guard's unwind from -40, 8 threads under the guard, unwind.
    'v4b': [('b_4t', -40, 4, 30), ('g_cool', None, 0, 15), ('g_8t', None, 8, 20), ('g_unwind8', None, 0, 25)],
    # 21:08: at 4 threads -40 kept the PSU tone out of the band but was ~1 dB(A) LOUDER than the guard's -80 (system fans
    # 2,900 vs 1,600 rpm). Return to -80 (A/B/A) before deciding; forced -80, since the guard would hold -40 after b_4t.
    'v4a2': [('a2_4t', -80, 4, 20), ('g_unwind', None, 0, 15)],
    # 21:29: A2 confirms (-80 -66.9 / -67.0 dB(A) with the 782 Hz whine, -40 -66.0 without it). Is there an offset in
    # between that keeps the PSU tone under the band without the -40 fan cost? -60, 25 min (load off by 21:56).
    'v4c': [('c_4t', -60, 4, 25), ('g_unwind', None, 0, 15)],
    'v4idle': [('g_idle', None, 0, 600)],
    # 2026-10-13 afternoon: the guard (v2.4) in control through what ryuji will really see. A 30 min full load (does
    # it hold -60 without throttling, and how does it start from -80?), its unwind, bursts (3 min on / 4 min off:
    # no flip-flop wanted), half load, then the benchmark window (bench-1013.sh adds 7-Zip's load alongside).
    'v24val': [('g_idle', None, 0, 10), ('g_full', None, 44, 30), ('g_unwind', None, 0, 20),
               ('g_b1', None, 44, 3), ('g_b1o', None, 0, 4), ('g_b2', None, 44, 3), ('g_b2o', None, 0, 4),
               ('g_b3', None, 44, 3), ('g_b3o', None, 0, 4), ('g_b4', None, 44, 3), ('g_bunwind', None, 0, 20),
               ('g_half', None, 22, 15), ('g_hunwind', None, 0, 15)],
    # v2.5 validation (guard in control): full load from idle (expect no change from -80), half load (expect -60 within
    # ~3 min), the half load growing to full (expect -80 again ~5 min later), bursts of full load (expect no change).
    'v25val': [('g_idle', None, 0, 10), ('g_full', None, 44, 30), ('g_unwind', None, 0, 15),
               ('g_half', None, 22, 20), ('g_grow', None, 44, 15), ('g_unwind2', None, 0, 15),
               ('g_b1', None, 44, 3), ('g_b1o', None, 0, 4), ('g_b2', None, 44, 3), ('g_b2o', None, 0, 4),
               ('g_b3', None, 44, 3), ('g_b3o', None, 0, 4), ('g_b4', None, 44, 3), ('g_bunwind', None, 0, 10)],
    'v4bench': [('g_bench', None, 0, 16), ('g_bcool', None, 0, 15)],
    # 13:35: under the guard, 20 min of 22 workers at -60 ended with the PSU tone at 729 Hz (in the band), -64.01 dB(A);
    # the 8 min profile hold at -60 had shown 442 Hz, likely before the PSU had warmed. Settle half load with 20 min holds:
    # A/B/A -80 / -60 / -80, load held through, then a guard cool-down. Sets v2.5's BUSY_PKG_MAX (22 workers = 188 W).
    'v4half': [('k80_22t_a', -80, 22, 20), ('k60_22t', -60, 22, 20), ('k80_22t_b', -80, 22, 20), ('k_cool', None, 0, 10)],
    # 11:00: at full load -80 was 2.7 dB(A) quieter than -60 (CPU 74 vs 72C), at 22 workers -60 was better (no whine).
    # Where is the crossover? 33 workers (three quarters), A/B/A with the load held through, then a guard cool-down.
    'v4heavy': [('h60_33t', -60, 33, 8), ('h80_33t', -80, 33, 8), ('h60_33t_b', -60, 33, 8), ('h_cool', None, 0, 10)],
    # 2026-10-13 (Rohit out, testing until 16:30; guard v2.4 deployed 04:41: BUSY -60 on >= 2 busy threads).
    # Morning: does 2 threads already need -60 (BUSY_THREADS 2 or 3)? A/B/A at 2 threads, then v2.4's live check at 4.
    'v24light': [('g_ref', None, 0, 10), ('t2_a1', -80, 2, 20), ('t2_b', -60, 2, 20), ('t2_a2', -80, 2, 20),
                 ('g_cool', None, 0, 15), ('g_4t', None, 4, 25), ('g_unwind', None, 0, 15)],
    # Full-load profile on the E5-2696 v4s (METHODOLOGY step 3, shortened): the guard's levels, loudest first, each
    # idle / half (22 workers) / full (44 = one per core); 88 workers (every thread) at 0 for the most heat; 11 workers
    # at -60 (the guard's level for a medium job); Full Speed (127) at full load; -80 idle bracket.
    'v4prof': [('p0_idle', 0, 0, 8), ('p0_22t', 0, 22, 8), ('p0_44t', 0, 44, 8), ('p0_88t', 0, 88, 6),
               ('p16_idle', -16, 0, 8), ('p16_22t', -16, 22, 8), ('p16_44t', -16, 44, 8),
               ('p60_idle', -60, 0, 8), ('p60_11t', -60, 11, 8), ('p60_22t', -60, 22, 8), ('p60_44t', -60, 44, 8),
               ('p80_idle', -80, 0, 8), ('p80_22t', -80, 22, 8), ('p80_44t', -80, 44, 8),
               ('p127_idle', 127, 0, 4), ('p127_44t', 127, 44, 8), ('R80_idle', -80, 0, 10)],
    'full': [(f'o{o}_{w}t', o, w, m) for o in (0, -8, -16, -24, -80) for w, m in STEPS] + [('R80_idle', -80, 0, 8)],
    'rest0806': ([(f'o{o}_{w}t', o, w, m) for o in (-16, -8) for w, m in STEPS]
                 + [(f'o-24_{FULL}t', -24, FULL, 6)]
                 + [(f'o-80_{w}t', -80, w, m) for w, m in ((0, 8), (4, 6), (FULL, 6))]
                 + [('R80_idle', -80, 0, 8)]),
    # Final rack run 2026-10-14/16 (ryuji racked, mic on the mattress ~4 ft from the rack): 20 min holds
    # with the load held through (the PSU tone needs 10-25 min to settle), A/B/A against -80.
    # fin_light (Wednesday, medium window): does v2.6's -60 band still pay in the rack at 2, 4 and 11 workers?
    'fin_light': [('r_ref', G, 0, 10),
                  ('t2_a1', -80, 2, 20), ('t2_b', -60, 2, 20), ('t2_a2', -80, 2, 20), ('t2_cool', G, 0, 10),
                  # Rohit 10-13 21:5x: in the living room it must pass for the A/C, so a tone counts against an offset
                  # more than broadband does: -40 (tone pushed under the band, ~+1 dB broadband on 10-12) joins -60/-80.
                  ('t4_a1', -60, 4, 20), ('t4_b', -80, 4, 20), ('t4_c', -40, 4, 20), ('t4_a2', -60, 4, 20),
                  ('t4_cool', G, 0, 10),
                  ('t11_a1', -60, 11, 20), ('t11_b', -80, 11, 20), ('t11_c', -40, 11, 20), ('t11_a2', -60, 11, 20),
                  ('g_unwind', G, 0, 15)],
    # fin_mixed: ryuji's half of an everyday medium mix (mementos 12 workers and a shelf read at the same time).
    'fin_mixed': [('x_ref', G, 0, 10), ('x_11w', G, 11, 45), ('x_unwind', G, 0, 20)],
    # fin_burstm: random medium-window loads under the guard (hunting check), then the unwind.
    'fin_burstm': [('bm_ref', G, 0, 5)] + seq(BURST_MED) + [('bm_unwind', G, 0, 20)],
    # fin_psu2 (Wed 19:00, in place of the medium bursts): ryuji on BOTH FSP800-20ERM supplies since 10-14 11:42
    # (Rohit seated the spare, so each carries about half the load). The same holds as fin_light's -80 phases, to
    # compare with the single-supply numbers of this morning: does the PSU whine drop?
    'fin_psu2': [('p_idle', G, 0, 10), ('p4', -80, 4, 20), ('p11', -80, 11, 20), ('p_unwind', G, 0, 5)],
    # fin_drive (Wed 14:40, after ryuji's drive soak hit 50C in 6 min at -80 with idle CPUs): how much do the system fans
    # cool the six MG04s? At idle CPU they leave their ~1,050 rpm floor only from -16 up (1,260 at -16, 1,650 at -8,
    # 2,240 at 0 on 10-06). Run with a disk-soak (random reads) beside it; the soak stops itself at 51C.
    'fin_drive': [('dP', 0, 0, 30), ('d8', -8, 0, 30), ('d16', -16, 0, 30), ('d_back', G, 0, 15)],
    # fin_idleoff (Thursday noise sweep): what each offset costs at idle, A/B against -80, 3 min each.
    'fin_idleoff': [('i80_a', -80, 0, 3), ('i127', -127, 0, 3), ('i80_b', -80, 0, 3), ('i60', -60, 0, 3),
                    ('i80_c', -80, 0, 3), ('i40', -40, 0, 3), ('i80_d', -80, 0, 3), ('i16', -16, 0, 3),
                    ('i80_e', -80, 0, 3), ('i0', 0, 0, 3), ('i80_f', -80, 0, 3)],
    # fin_heavy (Thursday): can an offset below -80 make 22-44 workers quieter, and at what CPU temperature?
    # fin_heavy1 (Friday 10-16, ryuji on ONE supply since 10-15): the validation run found 22 / 33 workers at -127 2.6-3.4
    # dB louder than fin_heavy's dual-supply holds (the lone supply's tone 823-858 Hz at -63/-64 dBFS); is -127 still
    # quieter than -80 with one supply? Same A/B/A, 20 min holds, in place of Friday's bursts.
    'fin_heavy1': [('h_ref', G, 0, 5),
                   ('k80_a', -80, 22, 20), ('k127', -127, 22, 20), ('k80_b', -80, 22, 20),
                   ('m80_a', -80, 33, 20), ('m127', -127, 33, 20), ('m80_b', -80, 33, 20), ('h_cool', G, 0, 10)],
    'fin_heavy': [('h_ref', G, 0, 5),
                  ('k80_a', -80, 22, 20), ('k127', -127, 22, 20), ('k80_b', -80, 22, 20), ('k_cool', G, 0, 10),
                  ('m80_a', -80, 33, 20), ('m127', -127, 33, 20), ('m80_b', -80, 33, 20),
                  ('f80_a', -80, 44, 15), ('f127', -127, 44, 15), ('f80_b', -80, 44, 15), ('h_cool', G, 0, 10)],
    # fin_comb (Thursday combined full tilt): 44 workers under the guard for 100 min while mementos steps up and every
    # drive soak runs (see mementos-steps fin_comb), then the unwind.
    'fin_comb': [('c_ref', G, 0, 3), ('c_44w', G, 44, 100), ('c_unwind', G, 0, 22)],
    # fin_val (Friday): every load level under the guard as deployed, then the unwind.
    'fin_val': [('v_idle', G, 0, 10), ('v2', G, 2, 15), ('v4', G, 4, 20), ('v11', G, 11, 20), ('v22', G, 22, 20),
                ('v33', G, 33, 20), ('v44', G, 44, 20), ('v_unwind', G, 0, 20)],
    'fin_burst': [('b_ref', G, 0, 5)] + seq(BURST_ALL) + [('b_unwind', G, 0, 20)],
    'fin_soak': [('s_ref', G, 0, 5), ('s_33w', G, 33, 120), ('s_unwind', G, 0, 25)],
    'dry': [('d_idle', G, 0, 1), ('d_1t', G, 1, 1), ('d_cool', G, 0, 1)],
}
PLAN = PLANS[sys.argv[2] if len(sys.argv) > 2 else 'floor']
# Room gating. makoto's lab-inlet-guard writes "<epoch> <mementos inlet>" to ROOM_FILE every minute. A load step
# starts only at <= ROOM_START (waits up to WAIT_MAX, else it is skipped) and its load is dropped above ROOM_STOP or
# if the reading is more than 3 min old. 10-06: Rohit's 27C rule until 08:4x, then up to 29C allowed.
ROOM_FILE, ROOM_START, ROOM_STOP, WAIT_MAX = '/run/room-inlet', 26, 27, 25 * 60
# 2026-10-12: LOAD_UNTIL (epoch, env) = no load step starts after it; the phase runs idle instead (a quiet night).
LOAD_UNTIL = float(os.environ.get('LOAD_UNTIL', 'inf'))
FAN_FLOOR = 1000
floor_hit = set()   # offsets that took a fan under FAN_FLOOR
# E5-2696 v4 (2026-10-12): BMC CPU thresholds 82 upper non-critical / 85 critical, coretemp high 83 / crit 85, so the
# CPU limits sit under them (were 82 / 86 on the E5-2650 v3s). 10-13 full-load profile: load off at the BMC's own
# warning (82; the evening's light tests used 80), Full Speed and exit at 84.
LOAD_STOP = {'sio1': 80, 'cpu': 82, 'vr': 95, 'dimm': 80}
ABORT = {'sio1': 83, 'cpu': 84}

def sh(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, timeout=60, **k)

def note(msg):
    with open(CSV, 'a') as f:
        f.write(f'# {int(time.time())} {time.strftime("%F %T %Z")} {msg}\n')
    print(msg, flush=True)

def set_offset(o):
    r = sh(*OFFSET_TOOL, 'set', str(o), env=ENV)
    got = re.search(r'now (-?\d+)', r.stdout)
    if r.returncode != 0 or not got or int(got.group(1)) != o:
        note(f'BMC set {o} failed (rc {r.returncode}: {r.stdout.strip()} {r.stderr.strip()[-200:]}); stopping')
        sys.exit(2)
    note(f'BMC offset set to {o}')

HDDS = [l.split()[0] for l in sh('lsblk', '-dno', 'NAME,ROTA,TYPE').stdout.splitlines()
        if l.split()[1:] == ['1', 'disk']]

def hdd_max():
    m = None
    for d in HDDS:
        o = sh('smartctl', '-n', 'standby', '-A', f'/dev/{d}').stdout
        x = re.search(r'^194 Temperature_Celsius(?:\s+\S+){7}\s+(\d+)', o, re.M)
        if x:
            m = max(m or 0, int(x.group(1)))
    return m

def sensors():
    t = {}
    for typ in ('Temperature', 'Fan'):
        for line in sh('ipmitool', 'sdr', 'type', typ).stdout.splitlines():
            f = [x.strip() for x in line.split('|')]
            m = re.match(r'(\d+) (degrees|RPM)', f[4]) if len(f) >= 5 else None
            if m:
                t[f[0]] = int(m.group(1))
    w = re.search(r'Instantaneous power reading:\s+(\d+)', sh('ipmitool', 'dcmi', 'power', 'reading').stdout)
    sysf = [v for k, v in t.items() if k.startswith('SYS_FAN')]
    fans = [v for k, v in t.items() if k.endswith('_FAN') or k.startswith('SYS_FAN')]
    return {
        'fan_min': min(fans) if fans else None,
        'cpu0': t.get('CPU0_TEMP'), 'cpu1': t.get('CPU1_TEMP'), 'sio1': t.get('SIO Temp 1'), 'sio2': t.get('SIO Temp 2'),
        'pch': t.get('PCH_TEMP'), 'vr': max((v for k, v in t.items() if k.startswith('VR_')), default=None),
        'dimm': max((v for k, v in t.items() if k.startswith('DIMM_')), default=None),
        'cpu_fan0': t.get('CPU0_FAN'), 'cpu_fan1': t.get('CPU1_FAN'),
        'sys_fan': round(sum(sysf) / len(sysf)) if sysf else None,
        'dcmi_w': int(w.group(1)) if w else None,
    }

ZONES = sorted(glob.glob('/sys/class/powercap/intel-rapl:[01]'))
def energy():
    return [int(open(f'{z}/energy_uj').read()) for z in ZONES]

stress = None
def load(pct):
    global stress
    if stress and stress.poll() is None:
        stress.terminate()
        try:
            stress.wait(15)
        except subprocess.TimeoutExpired:
            stress.kill()
    stress = None
    if pct:
        stress = subprocess.Popen(['nice', '-n', '10', 'stress-ng', '--cpu', str(pct), '--cpu-method', 'matrixprod',
                                   '--quiet'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def guard(on):
    sh('systemctl', 'start' if on else 'stop', 'ryuji-fan-guard')
    note(f'ryuji-fan-guard {"started" if on else "stopped"}')

def guard_offset():
    try:
        return re.search(r'"offset": (-?\d+)', open('/run/ryuji-fan-guard.state').read()).group(1)
    except (OSError, AttributeError):
        return ''

def room():
    try:
        t, v = open(ROOM_FILE).read().split()
        return int(v) if time.time() - int(t) < 180 else None
    except (OSError, ValueError):
        return None

cols = ['epoch', 'time_utc', 'phase', 'phase_min', 'offset', 'load', 'cpu0', 'cpu1', 'sio1', 'sio2', 'pch', 'vr', 'dimm',
        'hdd', 'cpu_fan0', 'cpu_fan1', 'sys_fan', 'fan_min', 'dcmi_w', 'pkg0_w', 'pkg1_w', 'room', 'thr_core', 'thr_pkg']

def throttles():
    """2026-10-13: cumulative thermal-throttle events (kernel thermal_throttle counters): all cores, and each package once"""
    core = pkg = 0
    seen = set()
    for d in glob.glob('/sys/devices/system/cpu/cpu[0-9]*'):
        try:
            core += int(open(f'{d}/thermal_throttle/core_throttle_count').read())
            p = open(f'{d}/topology/physical_package_id').read().strip()
            if p not in seen:
                seen.add(p)
                pkg += int(open(f'{d}/thermal_throttle/package_throttle_count').read())
        except (OSError, ValueError):
            pass
    return core, pkg

def fan_min_now():
    vals = []
    for line in sh('ipmitool', 'sdr', 'type', 'Fan').stdout.splitlines():
        f = [x.strip() for x in line.split('|')]
        m = re.match(r'(\d+) RPM', f[4]) if len(f) >= 5 else None
        if m:
            vals.append(int(m.group(1)))
    return min(vals) if vals else None

def floor_check(off, label):
    """True if the fans are fine at this offset; else back to -80 at once and mark the offset."""
    global current
    if off is None or off >= -80:
        return True
    fm = fan_min_now()
    if fm is not None and fm < FAN_FLOOR:
        set_offset(-80); current = -80
        floor_hit.add(off)
        note(f'{label}: a fan read {fm} rpm (< {FAN_FLOOR}) at offset {off}: back to -80; offsets <= {off} skipped')
        return False
    return True

def sel_count():
    m = re.search(r'Entries\s*:\s*(\d+)', sh('ipmitool', 'sel', 'info').stdout)
    return int(m.group(1)) if m else None
if not os.path.exists(CSV):
    with open(CSV, 'w') as f:
        f.write(','.join(cols) + '\n')

def log_row(label, off, t0, st, workers):
    """one sample: log it, apply the safety limits. st carries the energy counter between samples."""
    s = sensors()
    s['hdd'] = hdd_max()
    e1, tn = energy(), time.time()
    pw = [f'{(b - a) / 1e6 / (tn - st["tp"]):.1f}' if b >= a else '' for a, b in zip(st['e0'], e1)]
    st['e0'], st['tp'] = e1, tn
    cur = workers if stress and stress.poll() is None else 0
    tc, tp = throttles()
    row = dict(s, epoch=int(tn), time_utc=time.strftime('%T', time.gmtime(tn)), phase=label, phase_min=f'{(tn - t0) / 60:.1f}',
               thr_core=tc, thr_pkg=tp,
               offset=f'g{guard_offset()}' if off is None else off, load=cur,
               pkg0_w=pw[0] if pw else '', pkg1_w=pw[1] if len(pw) > 1 else '', room=room())
    with open(CSV, 'a') as f:
        f.write(','.join('' if row.get(c) is None else str(row.get(c)) for c in cols) + '\n')
    if s['sio1'] is None or s['cpu0'] is None:
        note('sensor read failed; stopping'); sys.exit(3)
    vals = dict(s, cpu=max(s['cpu0'] or 0, s['cpu1'] or 0))
    hot = [f'{k}={vals[k]}' for k, lim in ABORT.items() if vals[k] is not None and vals[k] >= lim]
    if hot:
        load(0)
        if guard_on:
            note(f'ABORT at {", ".join(hot)} (guard in control)')
        else:
            note(f'ABORT at {", ".join(hot)}: setting Full Speed'); set_offset(127)
        sys.exit(4)
    warm = [f'{k}={vals[k]}' for k, lim in LOAD_STOP.items() if vals[k] is not None and vals[k] >= lim]
    if warm and cur:
        load(0)
        note(f'{label}: load stopped ({", ".join(warm)})')
    r = row['room']
    if cur and (r is None or r > ROOM_STOP):
        load(0)
        note(f'{label}: load stopped (room {r}C)')

note(f'start {LABEL}; HDDs {HDDS}')
sel0 = sel_count()
note(f'BMC SEL entries at start: {sel0}')
fan_idle = {}   # offset -> median idle fan_min
guard_on = sh('systemctl', 'is-active', 'ryuji-fan-guard').stdout.strip() == 'active'
current = None   # offset this script last set (one BMC login per change, not per phase)
try:
    for label, off, pct, mins in PLAN:
        if off == LOW:
            off = next((o for o in (-127, -100) if o not in floor_hit and not any(h >= o for h in floor_hit)), None)
            if off is None:
                note('oLOW_full: skipped (no offset below -80 passed; o-80_full follows)')
                continue
            label = f'o{off}_full'
        if off is not None and off < -80 and any(h >= off for h in floor_hit):
            note(f'{label}: skipped (offset {off} is at or below one that hit the fan floor)')
            continue
        if off == -127 and -100 in fan_idle and -80 in fan_idle:
            proj = fan_idle[-100] - (fan_idle[-80] - fan_idle[-100]) * 27 / 20
            if proj < FAN_FLOOR:
                note(f'{label}: skipped (idle fans {fan_idle[-80]} at -80, {fan_idle[-100]} at -100 project {proj:.0f} rpm at -127)')
                floor_hit.add(-127)
                continue
        if off is None and not guard_on:
            guard(True); guard_on = True; current = None
        if off is not None:
            if guard_on:
                guard(False); guard_on = False
            if off != current:
                set_offset(off); current = off
                ok = True
                for _ in range(12):   # watch the first 60 s closely below -80
                    if off >= -80:
                        break
                    time.sleep(5)
                    if not floor_check(off, label):
                        ok = False
                        break
                if not ok:
                    continue
        st = {'e0': energy(), 'tp': time.time()}
        if pct and time.time() > LOAD_UNTIL:
            note(f'{label}: past LOAD_UNTIL, running it idle'); pct = 0
        if pct:
            r = room()
            if r is None or r > ROOM_START:
                note(f'{label}: room {r}C, waiting for <= {ROOM_START}C before adding load')
                tw = time.time()
                while (r is None or r > ROOM_START) and time.time() - tw < WAIT_MAX:
                    time.sleep(30)
                    log_row(label + '_wait', off, tw, st, 0)
                    r = room()
                if r is None or r > ROOM_START:
                    note(f'{label}: skipped (room {r}C after {WAIT_MAX // 60} min)')
                    continue
        load(pct)
        note(f'phase {label}: offset {"guard" if off is None else off}, {pct} busy threads, {mins} min, room {room()}C')
        t0 = time.time()
        fm_samples = []
        while time.time() - t0 < mins * 60:
            time.sleep(15 if pct else 30)   # 2026-10-13: faster under load (150 W CPUs heat ~5C per 30 s)
            log_row(label, off, t0, st, pct)
            if not floor_check(off, label):
                break
            fmv = fan_min_now()
            if fmv is not None and time.time() - t0 > (mins - 4) * 60:
                fm_samples.append(fmv)
        if pct == 0 and off is not None and fm_samples and label.startswith(f'o{off}_0t'):
            fan_idle[off] = sorted(fm_samples)[len(fm_samples) // 2]
            note(f'{label}: idle fan_min median {fan_idle[off]} rpm')
    if current is not None and current != -80:
        set_offset(-80); current = -80
    if not guard_on:
        guard(True)
    sel1 = sel_count()
    note(f'BMC SEL entries at end: {sel1} (start {sel0})')
    if sel0 is not None and sel1 is not None and sel1 > sel0:
        new = sh('ipmitool', 'sel', 'list').stdout.strip().splitlines()[-(sel1 - sel0):]
        note('new SEL entries: ' + ' || '.join(new))
    note('done')
finally:
    load(0)
