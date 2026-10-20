#!/bin/sh
# make-light F4: light-load holds (nice 19 matrixprod) with FAN1 stepped down from the BMC idle level, FAN4 fixed at F4
F4=$1
cat <<S
# light loads, FAN1 30 -> 20 -> 10 -> 1 %, FAN4 $F4 %, 4 workers only once the assistant has been idle 10 min
l1_f30 30 $F4 600 1
l1_f20 20 $F4 420 1
l1_f10 10 $F4 420 1
l1_f1 1 $F4 420 1
l2_f30 30 $F4 540 2
l2_f20 20 $F4 420 2
l2_f10 10 $F4 420 2
l2_f1 1 $F4 420 2
@gate 30 $F4 3600
l4_f30 30 $F4 540 4
l4_f20 20 $F4 420 4
l4_f10 10 $F4 420 4
l4_f1 1 $F4 420 4
cool 30 $F4 600 0
S
