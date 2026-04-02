find /home/pi/MACS/MACS -name "*.py" -exec grep -l '|' {} \; | while read f; do
    if ! head -5 "$f" | grep -q "from __future__ import annotations"; then
        sed -i '0,/^import\|^from/{s/^import\|^from/from __future__ import annotations\n&/}' "$f"
    fi
done