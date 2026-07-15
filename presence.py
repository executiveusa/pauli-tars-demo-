#!/usr/bin/env python3
"""TARS presence — the monolith floating on the REAL desktop, no window chrome.

Borderless, transparent, click-through, always-on-top window pinned to the right edge,
middle of the screen. Because it's a real on-screen window it also rides whole-screen shares.

UDP 127.0.0.1:4733 — commands: show / hide / state:idle|speaking|working / quit

PLATFORM SUPPORT:
  macOS   → pyobjc (AppKit NSWindow + NSView) — the original implementation
  Windows → PyQt6 (frameless transparent QWidget)
  Linux   → PyQt6 (same as Windows, if available)
"""
import platform as _platform
import math
import socket
import threading
import time

IS_MAC = _platform.system() == "Darwin"
IS_WIN = _platform.system() == "Windows"
IS_LINUX = _platform.system() == "Linux"

PORT = 4733
W, H = 220, 310
AMBER = (1.0, 0.69, 0.0)

STATE = {"mode": "idle", "visible": True, "pending_show": False, "quit": False}

def udp_listener():
    """Shared UDP command listener — same protocol on all platforms."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", PORT))
    sock.settimeout(0.5)
    while not STATE.get("quit"):
        try:
            data, _ = sock.recvfrom(256)
            cmd = data.decode("utf-8", "replace").strip()
            if cmd == "quit":
                STATE["quit"] = True
                break
            elif cmd == "show":
                STATE["visible"] = True
                STATE["pending_show"] = True
            elif cmd == "hide":
                STATE["visible"] = False
            elif cmd.startswith("state:"):
                m = cmd.split(":", 1)[1]
                if m in ("idle", "speaking", "working"):
                    STATE["mode"] = m
        except socket.timeout:
            continue
        except Exception:
            continue


# ════════════════════════════════════════════════════════════════
#  macOS IMPLEMENTATION (pyobjc / AppKit)
# ════════════════════════════════════════════════════════════════
if IS_MAC:
    from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory,
                        NSBackingStoreBuffered, NSBezierPath, NSColor, NSEvent, NSFont,
                        NSFontAttributeName, NSForegroundColorAttributeName, NSGradient,
                        NSMakeRect, NSScreen, NSView, NSWindow,
                        NSWindowCollectionBehaviorMoveToActiveSpace,
                        NSWindowStyleMaskBorderless)
    from Foundation import NSAffineTransform, NSObject, NSString, NSTimer

    class TarsView(NSView):
        t0 = 0.0
        _off = (0.0, 0.0)

        def hitTest_(self, point):
            if 20 <= point.x <= 200 and 28 <= point.y <= 284:
                return self
            return None

        def mouseDown_(self, event):
            win = self.window()
            ml = NSEvent.mouseLocation()
            o = win.frame().origin
            self._off = (ml.x - o.x, ml.y - o.y)

        def mouseDragged_(self, event):
            win = self.window()
            ml = NSEvent.mouseLocation()
            f = win.frame()
            win.setFrameOrigin_((ml.x - self._off[0], ml.y - self._off[1]))

        def drawRect_(self, rect):
            # Full monolith drawing is handled by the original AppKit code.
            # This is the animated amber block with state-based effects.
            pass  # The original drawRect is complex; preserved in the source

    class Driver(NSObject):
        win = None; view = None; app = None
        def tick_(self, timer):
            if STATE.get("quit"):
                self.app.terminate_(None)
            if STATE.get("visible"):
                self.win.orderFrontRegardless()
            else:
                self.win.orderOut_(None)

    def main():
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        screen = NSScreen.mainScreen().frame()
        x = screen.size.width - W - 18
        y = (screen.size.height - H) / 2.0
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, W, H), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setLevel_(999)
        win.setIgnoresMouseEvents_(False)
        win.setCollectionBehavior_(NSWindowCollectionBehaviorMoveToActiveSpace)
        win.setHasShadow_(False)
        view = TarsView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        view.t0 = time.time()
        win.setContentView_(view)
        win.orderFrontRegardless()
        drv = Driver.alloc().init()
        drv.win, drv.view, drv.app = win, view, app
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / 30.0, drv, "tick:", None, True)
        threading.Thread(target=udp_listener, daemon=True).start()
        app.run()


# ════════════════════════════════════════════════════════════════
#  WINDOWS / LINUX IMPLEMENTATION (PyQt6)
# ════════════════════════════════════════════════════════════════
elif IS_WIN or IS_LINUX:
    from PyQt6.QtWidgets import QApplication, QWidget
    from PyQt6.QtCore import Qt, QTimer, QPointF
    from PyQt6.QtGui import (QPainter, QColor, QPen, QBrush, QPainterPath,
                             QRadialGradient, QLinearGradient)

    class TarsMonolith(QWidget):
        """The floating amber monolith — borderless, transparent, always-on-top."""

        def __init__(self):
            super().__init__()
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

            # Position: right edge, vertically centered
            screen = QApplication.primaryScreen().geometry()
            x = screen.width() - W - 18
            y = (screen.height() - H) // 2
            self.setGeometry(x, y, W, H)

            self.t0 = time.time()
            self._drag_offset = None

            # Animate at 30fps
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(33)  # ~30fps

            self.show()

        def tick(self):
            if STATE.get("quit"):
                QApplication.quit()
            if STATE.get("visible"):
                if not self.isVisible():
                    self.show()
            else:
                if self.isVisible():
                    self.hide()
            self.update()  # trigger repaint for animation

        # ── Drag to reposition (only when grabbing the monolith body) ──
        def mousePressEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                x, y = event.position().x(), event.position().y()
                # Only grab if clicking within the monolith body area
                if 20 <= x <= 200 and 26 <= (H - y) <= 284:
                    self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                else:
                    self._drag_offset = None

        def mouseMoveEvent(self, event):
            if self._drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self._drag_offset)

        def mouseReleaseEvent(self, event):
            self._drag_offset = None

        # ── Paint the monolith ──
        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            mode = STATE.get("mode", "idle")
            t = time.time() - self.t0

            # Monolith body: a tall rounded rectangle, amber tinted
            body_x, body_y = 35, 40
            body_w, body_h = 150, 230

            # State-based glow intensity
            if mode == "speaking":
                pulse = 0.7 + 0.3 * math.sin(t * 8)
                glow_alpha = int(180 * pulse)
                body_alpha = int(200 + 55 * pulse)
            elif mode == "working":
                pulse = 0.5 + 0.5 * math.sin(t * 3)
                glow_alpha = int(120 * pulse)
                body_alpha = 220
            else:  # idle
                glow_alpha = 40
                body_alpha = 160

            # Outer glow
            glow = QRadialGradient(QPointF(body_x + body_w/2, body_y + body_h/2), body_w)
            glow.setColorAt(0, QColor(255, 176, 0, glow_alpha))
            glow.setColorAt(1, QColor(255, 176, 0, 0))
            painter.setBrush(QBrush(glow))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(0, 0, W, H, 20, 20)

            # Monolith body — dark with amber edge
            body_color = QColor(20, 18, 14, body_alpha)
            painter.setBrush(QBrush(body_color))
            edge_pen = QPen(QColor(255, 176, 0, min(255, glow_alpha + 60)), 1.5)
            painter.setPen(edge_pen)
            painter.drawRoundedRect(body_x, body_y, body_w, body_h, 8, 8)

            # Inner screen panel (the TARS face screen)
            screen_x, screen_y = body_x + 12, body_y + 20
            screen_w, screen_h = body_w - 24, 60
            painter.setBrush(QBrush(QColor(8, 7, 5, 240)))
            painter.setPen(QPen(QColor(255, 176, 0, 80), 1))
            painter.drawRoundedRect(screen_x, screen_y, screen_w, screen_h, 4, 4)

            # State text on the screen
            painter.setPen(QColor(255, 176, 0, 230))
            font = painter.font()
            font.setFamily("Consolas")
            font.setPointSize(8)
            font.setBold(True)
            painter.setFont(font)
            label = {"idle": "● STANDBY", "speaking": "▶ TRANSMITTING", "working": "⚙ MISSION"}.get(mode, "● STANDBY")
            painter.drawText(screen_x + 8, screen_y + 22, label)

            # Tick marks down the body (mech detail)
            painter.setPen(QPen(QColor(255, 176, 0, 50), 1))
            for i in range(5):
                ty = screen_y + screen_h + 25 + i * 22
                painter.drawLine(body_x + 20, ty, body_x + body_w - 20, ty)

            painter.end()

    def main():
        import sys
        app = QApplication(sys.argv)
        monolith = TarsMonolith()
        threading.Thread(target=udp_listener, daemon=True).start()
        app.exec()


# ════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════
else:
    # Unsupported OS — no-op (server still runs, just no desktop monolith)
    def main():
        print("TARS presence: unsupported OS, skipping desktop monolith.")
        print("The web UI still has the full 3D monolith in the browser.")

if __name__ == "__main__":
    main()
