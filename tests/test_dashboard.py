"""Actual browser + local HTTP server. The ledger is explicitly an in-memory test double."""
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect

from test_integration import research, ledger, server


@pytest.fixture
def page():
    with sync_playwright() as playwright:
        executable = os.environ.get('TEST_BROWSER_EXECUTABLE')
        browser = playwright.chromium.launch(headless=True, **({'executable_path':executable} if executable else {}))
        page = browser.new_page(viewport={'width':1280,'height':1000})
        yield page
        browser.close()


def test_judge_workflow_and_tamper_detection(page, server, tmp_path):
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(server)
    expect(page.locator('#network')).to_contain_text('redsigma.testnet')
    expect(page.locator('#researchStatus')).to_contain_text('Descriptive evidence')
    page.get_by_role('button',name='Generate result',exact=True).click()
    expect(page.locator('#verification')).to_contain_text('Result loaded')
    assert page.locator('#charts img').count() == 4
    assert page.locator('#charts img').evaluate_all('(images) => images.every(i => i.complete && i.naturalWidth > 0)')
    with page.expect_download() as download:
        page.get_by_role('button',name='Download result').click()
    downloaded = tmp_path/'download.json'
    download.value.save_as(downloaded)
    assert json.loads(downloaded.read_text(encoding='utf-8'))['schema'] == 'near-thesis-result/v1'
    page.get_by_role('button',name='Submit to Sealed Log').click()
    expect(page.locator('#transaction')).to_contain_text('fixture-tx-1')
    expect(page.locator('#verification')).to_contain_text('VERIFIED:')
    page.get_by_role('button',name='Retrieve + verify').click()
    expect(page.locator('#verification')).to_contain_text('VERIFIED:')
    original = page.locator('#candidate').input_value()
    page.locator('#candidate').fill(original + '!')
    page.get_by_role('button',name='Retrieve + verify').click()
    expect(page.locator('#verification')).to_contain_text('MISMATCH:')
    page.locator('#entryId').fill('999')
    page.get_by_role('button',name='Retrieve + verify').click()
    expect(page.locator('#verification')).to_contain_text('NOT FOUND:')
    page.get_by_role('button',name='Load ledger page').click()
    expect(page.locator('#entries')).to_contain_text('signer.testnet')
    page.reload()
    expect(page.locator('#transaction')).to_contain_text('Previous transaction: fixture-tx-1')
    assert errors == []
    screenshot = os.environ.get('TEST_SCREENSHOT_PATH')
    if screenshot:
        page.screenshot(path=screenshot,full_page=True)


def test_browser_load_xss_and_rpc_failure(page, server, tmp_path):
    page.goto(server)
    expect(page.locator('#researchStatus')).to_contain_text('Descriptive evidence')
    attack = '<img src=x onerror="window.injected=true">'
    result = {'schema':'near-thesis-result/v1','demo':True,'status':attack,'thesis':attack,
              'evidence':{'chart_manifest':{'charts':[{'name':attack,'query':attack,'source':attack,'takeaway':attack}]}}}
    file = tmp_path/'loaded.json'
    file.write_text(json.dumps(result),encoding='utf-8')
    page.locator('#load').set_input_files(file)
    expect(page.locator('#researchStatus')).to_have_text(attack)
    assert page.evaluate('window.injected') is None
    assert page.locator('img[onerror]').count() == 0
    page.route('**/api/verify',lambda route:route.fulfill(status=502,content_type='application/json',body='{"error":"RPC unavailable"}'))
    page.locator('#entryId').fill('1')
    page.get_by_role('button',name='Retrieve + verify').click()
    expect(page.locator('#error')).to_have_text('RPC unavailable')
    expect(page.get_by_role('button',name='Retrieve + verify')).to_be_enabled()
    invalid = tmp_path/'invalid.json'
    invalid.write_text('{bad JSON',encoding='utf-8')
    page.locator('#load').set_input_files(invalid)
    expect(page.locator('#error')).not_to_be_empty()
