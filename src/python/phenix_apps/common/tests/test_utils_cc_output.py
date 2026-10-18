from phenix_apps.common import utils


def test_mm_exec_wait_reports_missing_output_as_empty_strings(monkeypatch):
    # A command that prints nothing gets no stdout row; callers then call
    # .encode() or json.loads() on the result, so it must be "" and not None.
    monkeypatch.setattr(utils, "mm_cc_filter_vm", lambda *_, **__: ("u-1", "kn-0"))
    monkeypatch.setattr(utils, "mm_command_id_for_host", lambda *_: "7")
    monkeypatch.setattr(utils, "mm_wait_for_cmd", lambda **_: None)
    monkeypatch.setattr(
        utils, "mm_cc_exitcode_wait", lambda *_, **__: {"Response": "0"}
    )
    monkeypatch.setattr(utils, "mm_cc_all_hosts", lambda *_, **__: [])

    class _MM:
        def cc_exec_once(self, _cmd):
            return []

        def cc_responses(self, _cmd_id):
            return []

    result = utils.mm_exec_wait(_MM(), "vm1", "true")

    assert result["stdout"] == ""
    assert result["stderr"] == ""
