"""Keeps gamepads from vibrating while the player runs.

A controller that connects as the H.264 core loads can rumble for about 30 seconds. The player has no use for rumble, so it sets the gain of every
force-feedback gamepad to zero (the Linux input subsystem's master volume for effects) and puts it back to full when it leaves.
"""
import glob
import os
import struct
import threading

EV_FF, FF_GAIN = 0x15, 0x60


def gain_event(value):
    """One input_event (this machine's layout) that sets the force-feedback gain: 0 is silent, 0xFFFF full."""
    return struct.pack('llHHi', 0, 0, EV_FF, FF_GAIN, value)


def ff_devices(root='/sys/class/input', dev='/dev/input'):
    """The event device files of the gamepads that can rumble."""
    out = []
    for path in sorted(glob.glob(os.path.join(root, 'event*'))):
        try:
            with open(os.path.join(path, 'device', 'capabilities', 'ff'), encoding='ascii') as f:
                if int(f.read().split()[0], 16):
                    out.append(os.path.join(dev, os.path.basename(path)))
        except (OSError, ValueError, IndexError):
            continue
    return out


def set_gain(value, devices=None):
    """Set the gain of each rumble-capable gamepad. -> how many accepted it."""
    done = 0
    for path in (ff_devices() if devices is None else devices):
        try:
            fd = os.open(path, os.O_WRONLY | getattr(os, 'O_NONBLOCK', 0))
        except OSError:
            continue
        try:
            os.write(fd, gain_event(value))
            done += 1
        except OSError:
            pass
        finally:
            os.close(fd)
    return done


class Mute:
    """Re-applies zero gain every couple of seconds, so a pad that connects later is silenced too."""

    def __init__(self, period=2.0):
        self.period, self.stopping = period, threading.Event()
        self.thread = threading.Thread(target=self._run, name='rumble-off', daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        while not self.stopping.is_set():
            set_gain(0)
            self.stopping.wait(self.period)

    def stop(self):
        self.stopping.set()
        set_gain(0xFFFF)
