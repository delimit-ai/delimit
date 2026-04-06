#!/bin/bash
# v4.20 Demo Script — recorded via asciinema for YouTube Short + GIF
# Shows: doctor → simulate → status → report flow
# Each command has a pause so the viewer can read the output

set -e

# Simulated typing effect
type_cmd() {
    echo ""
    echo -n "$ "
    for ((i=0; i<${#1}; i++)); do
        echo -n "${1:$i:1}"
        sleep 0.04
    done
    echo ""
    sleep 0.3
}

clear
echo ""
echo "  Delimit v4.20 — The Highest State of AI Governance"
echo "  ─────────────────────────────────────────────────────"
echo ""
sleep 2

# 1. Doctor
type_cmd "delimit doctor"
delimit doctor 2>/dev/null || node /home/delimit/npm-delimit/bin/delimit-cli.js doctor 2>/dev/null
sleep 3

# 2. Simulate
type_cmd "delimit simulate"
delimit simulate 2>/dev/null || node /home/delimit/npm-delimit/bin/delimit-cli.js simulate 2>/dev/null
sleep 3

# 3. Status
type_cmd "delimit status"
delimit status 2>/dev/null || node /home/delimit/npm-delimit/bin/delimit-cli.js status 2>/dev/null
sleep 3

# 4. Report
type_cmd "delimit report --since 7d"
delimit report --since 7d 2>/dev/null || node /home/delimit/npm-delimit/bin/delimit-cli.js report --since 7d 2>/dev/null
sleep 3

# 5. Remember
type_cmd "delimit remember 'v4.20 demo recorded successfully'"
delimit remember 'v4.20 demo recorded successfully' 2>/dev/null || node /home/delimit/npm-delimit/bin/delimit-cli.js remember 'v4.20 demo recorded successfully' 2>/dev/null
sleep 2

echo ""
echo "  npm i -g delimit-cli@4.20.0"
echo ""
sleep 3
