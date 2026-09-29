import importlib
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
monitor = importlib.import_module("monitor_cloud")


class FixedDateTime:
    current = datetime(2026, 9, 29, 15, 0)

    @classmethod
    def now(cls, _timezone=None):
        return cls.current


class DeliveryTests(unittest.TestCase):
    def test_market_window(self):
        with patch.object(monitor, "datetime", FixedDateTime):
            for hour, minute in [(9, 20), (10, 0), (11, 29), (13, 0), (14, 59)]:
                FixedDateTime.current = datetime(2026, 9, 29, hour, minute)
                self.assertTrue(monitor.market_open())
            for hour, minute in [(9, 0), (11, 30), (12, 0), (15, 0)]:
                FixedDateTime.current = datetime(2026, 9, 29, hour, minute)
                self.assertFalse(monitor.market_open())
            FixedDateTime.current = datetime(2026, 9, 27, 10, 0)
            self.assertFalse(monitor.market_open())

    def test_delayed_schedule_does_not_scan_or_push(self):
        command = {"add": None, "remove": None, "name": None}
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}), \
             patch.object(monitor, "market_open", return_value=False), \
             patch.object(monitor, "scan") as scan, \
             patch.object(monitor, "push") as push:
            monitor.do_run(command, False)
        scan.assert_not_called()
        push.assert_not_called()

    def test_deleted_remote_stock_is_not_pushed(self):
        command = {"add": None, "remove": None, "name": None}
        summary = {"code": "600011", "buySignals": [{"modelId": "m", "model": "m", "tf": "日线", "why": "test"}]}
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}), \
             patch.object(monitor, "market_open", return_value=True), \
             patch.object(monitor, "load_watchlist", return_value=[{"code": "600011", "name": "旧股票"}]), \
             patch.object(monitor, "scan", return_value=[summary]), \
             patch.object(monitor, "load_last_signals", return_value={"keys": []}), \
             patch.object(monitor, "cloud_watchlist_unchanged", return_value=False), \
             patch.object(monitor, "push") as push, \
             patch.object(monitor, "save_last_signals") as save:
            monitor.do_run(command, False)
        push.assert_not_called()
        save.assert_not_called()

    def test_failed_send_does_not_lose_signal(self):
        command = {"add": None, "remove": None, "name": None}
        summary = {"code": "600475", "buySignals": [{"modelId": "m", "model": "m", "tf": "日线", "why": "test"}]}
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}), \
             patch.object(monitor, "market_open", return_value=True), \
             patch.object(monitor, "load_watchlist", return_value=[{"code": "600475", "name": "华光环能"}]), \
             patch.object(monitor, "scan", return_value=[summary]), \
             patch.object(monitor, "load_last_signals", return_value={"keys": []}), \
             patch.object(monitor, "cloud_watchlist_unchanged", return_value=True), \
             patch.object(monitor, "push", return_value=False), \
             patch.object(monitor, "save_last_signals") as save:
            with self.assertRaisesRegex(RuntimeError, "定时微信推送失败"):
                monitor.do_run(command, False)
        save.assert_not_called()

    def test_scheduled_scan_reports_no_buy_signal(self):
        command = {"add": None, "remove": None, "name": None}
        summary = {"code": "600475", "buySignals": []}
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"}), \
             patch.object(monitor, "market_open", return_value=True), \
             patch.object(monitor, "load_watchlist", return_value=[{"code": "600475", "name": "华光环能"}]), \
             patch.object(monitor, "scan", return_value=[summary]), \
             patch.object(monitor, "load_last_signals", return_value={"keys": []}), \
             patch.object(monitor, "cloud_watchlist_unchanged", return_value=True), \
             patch.object(monitor, "push", return_value=True) as push:
            monitor.do_run(command, False)
        push.assert_called_once()
        self.assertIn("暂无买点", push.call_args.args[2])

    def test_manual_schedule_mode_is_market_gated(self):
        command = {"mode": "schedule", "add": None, "remove": None, "name": None}
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch"}), \
             patch.object(monitor, "market_open", return_value=False), \
             patch.object(monitor, "scan") as scan:
            monitor.do_run(command, False)
        scan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
