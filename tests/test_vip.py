"""Tests for hermes.vip module."""
import json
import pytest

from hermes.vip import (
    detect_vips,
    load_vips,
    save_vips,
    add_vip,
    remove_vip,
    load_vip_domains,
    save_vip_domains,
    add_vip_domain,
    remove_vip_domain,
    is_vip_domain,
    needs_refresh,
    _extract_emails,
)


class TestExtractEmails:
    def test_simple_email(self):
        assert _extract_emails("user@example.com") == ["user@example.com"]

    def test_name_and_email(self):
        assert _extract_emails("John Doe <john@example.com>") == ["john@example.com"]

    def test_multiple_emails(self):
        result = _extract_emails("a@b.com, c@d.com")
        assert len(result) == 2

    def test_empty_string(self):
        assert _extract_emails("") == []


class TestDetectVips:
    def test_empty_sent_returns_empty(self, config):
        assert detect_vips([], config) == []

    def test_detects_frequent_sender(self, config):
        messages = []
        for i in range(10):
            messages.append({
                "to": "vip@example.com",
                "date": "Tue, 11 Feb 2026 12:00:00 +0000",
                "threadId": f"thread_{i}",
            })
        vips = detect_vips(messages, config)
        assert len(vips) > 0
        assert vips[0]["email"] == "vip@example.com"

    def test_low_frequency_not_vip(self, config):
        messages = [{"to": "once@example.com", "date": "", "threadId": "t1"}]
        vips = detect_vips(messages, config)
        assert len(vips) == 0


class TestVipPersistence:
    def test_save_and_load_vips(self, config):
        vips = [{"email": "a@b.com", "score": 50.0}]
        save_vips(vips, config)
        loaded = load_vips(config)
        assert len(loaded) == 1
        assert loaded[0]["email"] == "a@b.com"

    def test_load_nonexistent_returns_empty(self, config):
        assert load_vips(config) == []

    def test_add_vip(self, config):
        add_vip("new@example.com", config)
        vips = load_vips(config)
        assert any(v["email"] == "new@example.com" for v in vips)

    def test_add_duplicate_vip_no_duplicate(self, config):
        add_vip("dup@example.com", config)
        add_vip("dup@example.com", config)
        vips = load_vips(config)
        count = sum(1 for v in vips if v["email"] == "dup@example.com")
        assert count == 1

    def test_remove_vip(self, config):
        add_vip("remove@example.com", config)
        remove_vip("remove@example.com", config)
        vips = load_vips(config)
        assert not any(v["email"] == "remove@example.com" for v in vips)


class TestVipDomains:
    def test_save_and_load_domains(self, config):
        domains = [{"domain": "example.com", "company": "Example", "category": "tech"}]
        save_vip_domains(domains, config)
        loaded = load_vip_domains(config)
        assert len(loaded) == 1
        assert loaded[0]["domain"] == "example.com"

    def test_add_domain(self, config):
        add_vip_domain("test.com", "Test Co", "tech", config)
        domains = load_vip_domains(config)
        assert any(d["domain"] == "test.com" for d in domains)

    def test_remove_domain(self, config):
        add_vip_domain("remove.com", "Remove Co", "tech", config)
        remove_vip_domain("remove.com", config)
        domains = load_vip_domains(config)
        assert not any(d["domain"] == "remove.com" for d in domains)

    def test_is_vip_domain_match(self):
        domains = [{"domain": "vip.com", "company": "VIP", "category": "ent"}]
        assert is_vip_domain("user@vip.com", domains) is True

    def test_is_vip_domain_no_match(self):
        domains = [{"domain": "vip.com", "company": "VIP", "category": "ent"}]
        assert is_vip_domain("user@other.com", domains) is False


class TestNeedsRefresh:
    def test_no_file_needs_refresh(self, config):
        assert needs_refresh(config) is True

    def test_fresh_data_no_refresh(self, config):
        save_vips([{"email": "a@b.com", "score": 10.0}], config)
        assert needs_refresh(config) is False

    def test_corrupted_file_needs_refresh(self, config):
        config.vip_data_path.write_text("not json")
        assert needs_refresh(config) is True
