"""Doctor logic against fake /proc/bus/input/devices data (no hardware needed)."""
import os, tempfile
import swipepen.doctor as d

PROC = '''I: Bus=0003 Vendor=046d Product=c52b Version=0111
N: Name="Logitech USB Receiver"
H: Handlers=kbd event3

I: Bus=0003 Vendor=056a Product=0302 Version=0100
N: Name="Wacom Bamboo Pen Pen"
H: Handlers=mouse2 event12

I: Bus=0003 Vendor=056a Product=0302 Version=0100
N: Name="Wacom Bamboo Pen Pad"
H: Handlers=kbd event11

I: Bus=0019 Vendor=0000 Product=0001 Version=0000
N: Name="Power Button"
H: Handlers=kbd event0 
'''

def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else "  " + str(detail)))
    assert ok

with tempfile.NamedTemporaryFile("w", delete=False) as fh:
    fh.write(PROC); path = fh.name
d.PROC_DEVICES = path

tabs = d.tablets_in_proc()
check("finds the Wacom pen and pad, ignores keyboards", [t[1] for t in tabs] == ["/dev/input/event12", "/dev/input/event11"], tabs)
pens = d.pen_nodes_in_proc()
check("pen nodes exclude the Pad", [p[1] for p in pens] == ["/dev/input/event12"], pens)

# /dev/input/event12 does not exist in the sandbox -> not readable -> access problem
check("tablet present but unreadable is reported as an access problem", d.tablet_access_problem() is True)

# now make the 'pen node' readable by pointing the fake at a file we can read
readable = tempfile.NamedTemporaryFile(delete=False).name
d.PROC_DEVICES = path
orig_access = os.access
os.access = lambda p, mode: True if p == "/dev/input/event12" else orig_access(p, mode)
check("readable tablet is not an access problem", d.tablet_access_problem() is False)
os.access = orig_access

# no tablet in the list at all
NO_TABLET = PROC.split("I: Bus=0003 Vendor=056a")[0] + "I: Bus=0019" + PROC.split("I: Bus=0019")[1]
assert "Wacom" not in NO_TABLET and "Bamboo" not in NO_TABLET
open(path, "w").write(NO_TABLET)
check("no tablet in the system is not an access problem", d.tablet_access_problem() is False)
report = d.format_report(d.run_checks())
check("report says the system sees no tablet", "sees no tablet at all" in report, report)

# unreadable tablet: report must say 'not allowed', not 'plug in'
open(path, "w").write(PROC)
report = d.format_report(d.run_checks())
check("report says tablet is seen but not readable", "you are not allowed to read it" in report, report)
check("report tells the user to rerun install.sh", "./install.sh" in report)
print("\nAll doctor tests passed.")
