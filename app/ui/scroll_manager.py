"""
ui/scroll_manager.py
=====================
Focus-based scroll router.

Behavior
--------
- Clicking inside the playlist / log zone → only that widget scrolls.
  Main canvas is fully blocked while a zone is active.
- Clicking outside all zones → main canvas scrolls normally.
- Edge fallback: if the active zone hits its top/bottom edge and you keep
  scrolling that way, it releases and the main canvas takes over.
- Speed: natural (raw delta / 60 on Windows/Mac, 3 units on Linux).

Implementation note
-------------------
Tkinter fires widget-level bindings BEFORE bind_all bindings.
CTk registers its own MouseWheel handlers at the widget level, which means
they fire first and can double-scroll or swallow events before we see them.

Solution: we bind our handler at the widget level too (with add="+") and
return "break" to stop CTk's handler from also running. The bind_all handler
on the main canvas handles the no-zone-active (main scroll) case, which is
unaffected because CTk's main canvas doesn't have its own wheel binding.
"""

from __future__ import annotations
import tkinter as tk
from typing import Callable

_ACTIVE_BORDER   = "#3B82F6"
_INACTIVE_BORDER = ""


def _safe_parent(w: tk.Widget) -> tk.Widget | None:
    try:
        name = w.winfo_parent()
        if not name:
            return None
        return w.nametowidget(name)
    except Exception:
        return None


def _in_subtree(widget: tk.Widget, root: tk.Widget) -> bool:
    w = widget
    while w is not None:
        if w is root:
            return True
        w = _safe_parent(w)
    return False


class _Zone:
    def __init__(
        self,
        click_root:    tk.Widget,
        get_target:    Callable,
        border_widget: tk.Widget | None,
        manager:       "ScrollManager",
        scroll_speed:  float = 1.0,
    ):
        self._get_target    = get_target
        self._border_widget = border_widget
        self._manager       = manager
        self._focused       = False
        self._click_root    = click_root
        self.scroll_speed   = scroll_speed

        self._bind_subtree(click_root)

    def _bind_subtree(self, widget: tk.Widget) -> None:
        try:
            widget.bind("<Button-1>",   self._on_click,   add="+")
            # Widget-level wheel binding fires BEFORE bind_all.
            # We handle the scroll here and return "break" so CTk's own
            # internal wheel handler (also widget-level) is suppressed.
            widget.bind("<MouseWheel>", self._on_wheel,   add="+")
            widget.bind("<Button-4>",   self._on_wheel,   add="+")
            widget.bind("<Button-5>",   self._on_wheel,   add="+")
            for child in widget.winfo_children():
                self._bind_subtree(child)
        except tk.TclError:
            pass

    def _on_click(self, _event) -> None:
        self._manager._set_active(self)

    def _on_wheel(self, event: tk.Event) -> str:
        """
        Handle scroll for this zone's widgets directly.
        Returns "break" to prevent CTk's internal handler from double-scrolling.
        The ScrollManager._route (bind_all) will also fire, but we return "break"
        from HERE which only stops widget-level propagation — bind_all still runs.
        To prevent _route from double-scrolling, _route checks if a zone handled it.
        """
        self._manager._zone_scroll(self, event)
        return "break"

    def activate(self) -> None:
        self._focused = True
        if self._border_widget:
            try:
                self._border_widget.configure(border_color=_ACTIVE_BORDER, border_width=2)
            except Exception:
                pass

    def deactivate(self) -> None:
        self._focused = False
        if self._border_widget:
            try:
                self._border_widget.configure(border_color=_INACTIVE_BORDER, border_width=0)
            except Exception:
                pass

    @property
    def focused(self) -> bool:
        return self._focused

    @property
    def target(self) -> tk.Widget | None:
        return self._get_target()

    def is_at_edge(self, direction: int) -> bool:
        target = self.target
        if target is None:
            return True
        try:
            first, last = target.yview()
            return first <= 0.0 if direction < 0 else last >= 1.0
        except Exception:
            return False


class ScrollManager:
    def __init__(self, main_canvas: tk.Canvas, root_widget: tk.Widget) -> None:
        self._main_canvas   = main_canvas
        self._root_widget   = root_widget
        self._zones: list[_Zone] = []
        self._active: _Zone | None = None
        self._zone_handled  = False   # flag so _route skips double-scroll

        # bind_all for the no-zone case (main canvas scroll).
        # Zone events are handled at widget level and set _zone_handled=True
        # so _route knows not to also scroll the main canvas.
        main_canvas.bind_all("<MouseWheel>", self._route, add="+")
        main_canvas.bind_all("<Button-4>",   self._route, add="+")
        main_canvas.bind_all("<Button-5>",   self._route, add="+")

        root_widget.bind("<Button-1>", self._on_root_click, add="+")

    # ------------------------------------------------------------------ #

    def register(
        self,
        click_root:    tk.Widget,
        scroll_target: tk.Widget,
        border_widget: tk.Widget | None = None,
        scroll_speed:  float = 1.0,
    ) -> None:
        self.register_dynamic(click_root, lambda t=scroll_target: t, border_widget, scroll_speed)

    def register_dynamic(
        self,
        click_root:    tk.Widget,
        get_target:    Callable,
        border_widget: tk.Widget | None = None,
        scroll_speed:  float = 1.0,
    ) -> None:
        zone = _Zone(click_root, get_target, border_widget, self, scroll_speed)
        self._zones.append(zone)

    def rebind_clicks(self, widget: tk.Widget) -> None:
        for zone in self._zones:
            if _in_subtree(widget, zone._click_root):
                zone._bind_subtree(widget)
                return
        for zone in self._zones:
            try:
                zone._bind_subtree(widget)
            except Exception:
                pass

    def bind_extra(self, widget: tk.Widget, click_root: tk.Widget) -> None:
        """
        Explicitly bind a widget (e.g. an inner tk.Text that winfo_children
        doesn't expose) to the zone that owns click_root.
        """
        for zone in self._zones:
            if zone._click_root is click_root:
                zone._bind_subtree(widget)
                return

    # ------------------------------------------------------------------ #

    def _set_active(self, zone: _Zone) -> None:
        if self._active is zone:
            return
        if self._active is not None:
            self._active.deactivate()
        self._active = zone
        zone.activate()

    def _on_root_click(self, event: tk.Event) -> None:
        for zone in self._zones:
            if _in_subtree(event.widget, zone._click_root):
                return
        self.release()

    def release(self) -> None:
        if self._active is not None:
            self._active.deactivate()
            self._active = None

    # ------------------------------------------------------------------ #
    #  Scroll helpers                                                      #
    # ------------------------------------------------------------------ #

    def _direction(self, event: tk.Event) -> int:
        if event.num == 4:  return -1
        if event.num == 5:  return  1
        return -1 if event.delta > 0 else 1

    def _do_scroll(self, target: tk.Widget, event: tk.Event, speed: float = 1.0) -> None:
        if event.num in (4, 5):
            target.yview_scroll(-1 if event.num == 4 else 1, "units")
        else:
            units = int(-event.delta / 4 * speed)
            if units == 0:
                units = -1 if event.delta > 0 else 1
            target.yview_scroll(units, "units")

    def _zone_scroll(self, zone: _Zone, event: tk.Event) -> None:
        """
        Called from a zone's widget-level handler.
        Activates the zone if needed, scrolls it (or releases to main on edge),
        and sets _zone_handled so _route doesn't double-scroll.
        """
        self._zone_handled = True
        self._set_active(zone)

        direction = self._direction(event)
        if zone.is_at_edge(direction):
            self.release()
            self._do_scroll(self._main_canvas, event)
        else:
            target = zone.target
            if target is not None:
                self._do_scroll(target, event, zone.scroll_speed)
            else:
                self._do_scroll(self._main_canvas, event)

    def _route(self, event: tk.Event) -> str:
        """
        bind_all handler — fires for every widget.
        If a zone already handled this event at widget level, skip.
        Otherwise scroll the main canvas.
        """
        if self._zone_handled:
            # Zone widget handler already ran — reset flag and do nothing.
            self._zone_handled = False
            return "break"

        # No zone handled it — scroll main canvas (unless a zone is active,
        # in which case block main scroll entirely).
        if self._active is None:
            self._do_scroll(self._main_canvas, event)

        return "break"
