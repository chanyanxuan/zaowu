import requests, time, sys

B = 'http://127.0.0.1:5000'

def run(note, code_model, label):
    print(f'\n===== {label} =====', flush=True)
    bal = requests.get(B + '/api/credits').json()['balance']
    if bal < 20:
        requests.post(B + '/api/recharge', json={'amount': 10})
    t0 = time.time()
    r = requests.post(B + '/api/generate', data={'note': note, 'code_model': code_model}, timeout=15)
    j = r.json()
    if 'job_id' not in j:
        print('  失败:', j, flush=True)
        return
    jid = j['job_id']
    last = ''
    for _ in range(240):
        time.sleep(2)
        s = requests.get(B + '/api/status/' + jid).json()
        st = s.get('stage') or ''
        if st != last:
            print('  [阶段]', st, flush=True)
            last = st
        if s['status'] == 'awaiting_clarification':
            qs = s['questions'] or []
            ans = [{'field': q['field'], 'answer': (q.get('options') or [''])[0]} for q in qs]
            requests.post(B + '/api/answer', json={'job_id': jid, 'answers': ans})
            print('  [追问] 已自动选第一个选项', flush=True)
        elif s['status'] == 'done':
            print('  OK 成功, 耗时 %.0f 秒, 产物 %s' % (time.time() - t0, s['result']['name']), flush=True)
            return
        elif s['status'] == 'error':
            print('  FAIL 失败, 耗时 %.0f 秒' % (time.time() - t0), flush=True)
            print('  错误:', (s['error'] or '')[:300], flush=True)
            return
    print('  超时(>480s)', flush=True)


if __name__ == '__main__':
    run('设计一个齿轮减速箱外壳,分为上盖和下壳两个零件,整体约120×80×60毫米,壁厚2.5毫米,下壳底面四角4个M4安装孔,内部四角4根直径6毫米高30毫米螺丝柱带M3螺孔,一侧直径20毫米轴承座凸台,外壁四周6条厚2毫米高8毫米加强筋,上盖四角4个M3通孔,顶部40×20毫米观察窗口,外棱倒角R3',
        'deepseek-v4-flash', '减速箱外壳(快速)')
