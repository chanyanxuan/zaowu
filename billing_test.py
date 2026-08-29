import requests, time

B = 'http://127.0.0.1:5000'

print('生成前余额:', requests.get(B + '/api/credits').json()['balance'])

# 确保余额足够
bal = requests.get(B + '/api/credits').json()['balance']
if bal < 5:
    requests.post(B + '/api/recharge', json={'amount': 10})
    print('已充值 10 元, 余额:', requests.get(B + '/api/credits').json()['balance'])

t0 = time.time()
r = requests.post(B + '/api/generate', data={'note': '一个80×40×6毫米的固定夹片,两端各一个M3通孔', 'code_model': 'deepseek-v4-flash'}, timeout=15)
j = r.json()
print('generate:', j)
jid = j.get('job_id')
if not jid:
    raise SystemExit('生成失败')

for _ in range(200):
    time.sleep(2)
    s = requests.get(B + '/api/status/' + jid).json()
    if s['status'] == 'awaiting_clarification':
        qs = s['questions'] or []
        requests.post(B + '/api/answer', json={'job_id': jid, 'answers': [{'field': q['field'], 'answer': (q.get('options') or [''])[0]} for q in qs]})
    elif s['status'] == 'done':
        res = s['result']
        print(f"完成: tokens={res.get('tokens')} | 扣积分={res.get('points_used')} | 扣后余额={res.get('balance')}")
        print(f"耗时 {time.time()-t0:.0f}s")
        break
    elif s['status'] == 'error':
        print('失败:', s['error'][:200])
        break
else:
    print('超时')

print('最终余额:', requests.get(B + '/api/credits').json()['balance'])
print('流水:')
for t in requests.get(B + '/api/credits').json()['history'][:3]:
    print('  ', t['type'], t['points'], t.get('reason',''))
