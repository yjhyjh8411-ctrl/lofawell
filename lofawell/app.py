import os
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime
from werkzeug.utils import secure_filename
import firebase_admin
from firebase_admin import credentials, firestore, storage

app = Flask(__name__)
app.secret_key = 'lofa_infra_final_perfect_2026'

# --- [Firebase 초기화] ---
try:
    # 경로를 본인의 환경에 맞게 수정하세요 (예: 'serviceAccountKey.json')
    if os.path.exists('lofawell/serviceAccountKey.json'):
        cred = credentials.Certificate('lofawell/serviceAccountKey.json')
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'lofa-43d38.firebasestorage.app'
        })
    else:
        firebase_admin.initialize_app(options={
            'storageBucket': 'lofa-43d38.firebasestorage.app'
        })
    db = firestore.client()
    bucket = storage.bucket()
    print("Firebase Cloud 연결 성공")
except Exception as e:
    print(f"Firebase 연결 실패: {e}")

# --- [유틸리티 함수] ---
def upload_file_to_storage(file, user_id, user_name, apply_type):
    """Firebase Storage에 파일을 업로드하고 공개 URL을 반환합니다."""
    if not file or file.filename == '':
        return ""
    
    now_date = datetime.now().strftime('%Y%m%d_%H%M%S')
    original_name = secure_filename(file.filename)
    filename = f"{user_id}_{user_name}_{apply_type}_{now_date}_{original_name}"
    
    blob = bucket.blob(f"uploads/{filename}")
    blob.upload_from_string(file.read(), content_type=file.content_type)
    
    # 파일 접근 권한 설정 (공개 읽기 허용)
    blob.make_public()
    return blob.public_url

# --- [1. 로그인 및 세션] ---
@app.route('/')
def index():
    if 'user_id' in session:
        return render_template('main.html', user_name=session['user_name'])
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    try:
        sid = str(request.form['employeeId']).strip()
        pw = str(request.form['password']).strip()
        
        # Firestore에서 유저 확인
        user_ref = db.collection('users').document(sid).get()
        
        if user_ref.exists:
            u_info = user_ref.to_dict()
            if u_info['비밀번호'] == pw:
                session.update({
                    'user_id': sid,
                    'user_name': u_info['이름'],
                    'user_dept': u_info.get('부서', ''),
                    'user_rank': u_info.get('직급', ''),
                    'user_join_date': u_info.get('입사일', '')
                })
                return jsonify({"status": "success", "is_admin": sid == "admin"})
        
        return jsonify({"status": "error", "message": "사번 또는 비밀번호가 일치하지 않습니다."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"로그인 중 오류: {e}"})

# --- [2. 신청서 페이지 로드] ---
@app.route('/apply/<page>')
def apply_page(page):
    if 'user_id' not in session:
        return redirect(url_for('index'))

    edit_app_id = request.args.get('edit_app_id')
    data, edit_mode = None, False

    if edit_app_id:
        doc = db.collection('applications').document(edit_app_id).get()
        if doc.exists:
            data = doc.to_dict()
            edit_mode = True

    if not data:
        data = {
            '사번': session.get('user_id'),
            '성명': session.get('user_name'),
            '부서': session.get('user_dept'),
            '직급': session.get('user_rank'),
            '입사일': session.get('user_join_date')
        }

    return render_template(f'{page}.html', user_name=session['user_name'], edit_mode=edit_mode, data=data)

# --- [3. 신청서 제출 (Firestore 저장)] ---
@app.route('/submit', methods=['POST'])
@app.route('/edit_submit', methods=['POST'])
def handle_submit():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "세션 만료"})
    
    try:
        user_id = str(session.get('user_id'))
        user_name = str(session.get('user_name'))
        apply_type = request.form.get('type')
        
        # 1. 파일 처리
        file = request.files.get('attachment')
        file_url = request.form.get('old_filename', '') # 수정 시 기존 URL 유지
        
        if file and file.filename != '':
            file_url = upload_file_to_storage(file, user_id, user_name, apply_type)

        # 2. 데이터 구성
        amount_raw = str(request.form.get('amount', '0')).replace(',', '')
        amount_val = int(float(amount_raw)) if amount_raw.replace('.', '', 1).isdigit() else 0
        
        detail_parts = [
            f"항목:{request.form.get('item_name', '')}",
            f"금융:{request.form.get('bank_name', '')}",
            f"본인부담:{request.form.get('self_pay', '0')}",
            f"지원구분:{request.form.get('target_name', '')}",
            f"내용:{request.form.get('detail_text', '')}"
        ]
        clean_detail = " / ".join(p for p in detail_parts if not p.endswith(':') and not p.endswith(':0'))

        app_id = request.form.get('app_id')
        if not app_id or app_id == 'None':
            app_id = str(int(datetime.now().timestamp() * 1000))
            msg = "신청이 완료되었습니다."
        else:
            msg = "수정이 완료되었습니다."

        new_data = {
            'app_id': app_id,
            '신청일시': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '구분': apply_type,
            '부서': request.form.get('user_dept'),
            '사번': user_id,
            '직급': request.form.get('position'),
            '성명': user_name,
            '입사일': request.form.get('joinDate', ''),
            '전화번호': request.form.get('phone', ''),
            '신청금액': amount_val,
            '계좌번호': request.form.get('account', ''),
            '세부내용': clean_detail,
            '상태': '대기',
            '반려의견': '',
            '대상자성명': request.form.get('target_name', ''),
            '첨부파일': file_url # 이제 파일명 대신 URL 저장
        }

        # 3. Firestore 저장 (Upsert)
        db.collection('applications').document(app_id).set(new_data)
        
        return jsonify({"status": "success", "message": msg})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# --- [4. 현황 및 관리자 페이지] ---
@app.route('/my_status')
def my_status():
    if 'user_id' not in session: return redirect(url_for('index'))
    
    docs = db.collection('applications').where('사번', '==', str(session['user_id'])).stream()
    applications = [doc.to_dict() for doc in docs]
    applications.sort(key=lambda x: x['신청일시'], reverse=True)
    
    return render_template('my_status.html', user_name=session['user_name'], applications=applications)

@app.route('/admin')
def admin_dashboard():
    if session.get('user_id') != 'admin': return redirect(url_for('index'))
    
    cats = ['장학금지원', '경조비지원', '선진산업시찰', '주택지원', '복지연금', '의료비지원', '모성보호지원', '다자녀가정지원', '위로금지원', '생활복지지원']
    docs = db.collection('applications').stream()
    all_apps = [doc.to_dict() for doc in docs]
    
    # 관리자용 데이터 가공 (요약 및 통계)
    summary = {}
    stats = {'total': len(all_apps), 'wait': 0, 'approve': 0, 'reject': 0}
    
    for app_item in all_apps:
        # 통계 계산
        status = app_item.get('상태')
        if status == '대기': stats['wait'] += 1
        elif status == '승인': stats['approve'] += 1
        elif status == '반려': stats['reject'] += 1
        
        # 유저별 그룹화
        user_key = (app_item['사번'], app_item['성명'])
        if user_key not in summary:
            summary[user_key] = {cat: [] for cat in cats}
            summary[user_key]['사번'] = app_item['사번']
            summary[user_key]['성명'] = app_item['성명']
        
        cat = app_item['구분']
        if cat in cats:
            summary[user_key][cat].append({
                'app_id': app_item['app_id'],
                'amount': format(app_item.get('신청금액', 0), ','),
                'status': status,
                'apply_date': app_item['신청일시'],
                'detail': app_item
            })

    return render_template('admin.html', summary=list(summary.values()), categories=cats, stats=stats, user_name=session['user_name'])

@app.route('/admin_process', methods=['POST'])
def admin_process():
    if session.get('user_id') != 'admin': return jsonify({"status": "error"})
    
    app_id = request.form.get('app_id')
    status = request.form.get('status')
    reason = request.form.get('reason', '')
    
    db.collection('applications').document(app_id).update({
        '상태': status,
        '반려의견': reason
    })
    return jsonify({"status": "success"})

# --- [5. 회원가입 및 로그아웃] ---
@app.route('/signup_process', methods=['POST'])
def signup_process():
    sid = str(request.form.get('employeeId')).strip()
    user_ref = db.collection('users').document(sid).get()
    
    if user_ref.exists:
        return jsonify({"status": "error", "message": "이미 등록된 사번입니다."})
    
    new_user = {
        '사번': sid,
        '비밀번호': request.form.get('password'),
        '이름': request.form.get('userName'),
        '직급': request.form.get('position'),
        '부서': request.form.get('department'),
        '입사일': request.form.get('joinDate')
    }
    db.collection('users').document(sid).set(new_user)
    return jsonify({"status": "success"})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/signup')
def signup_page():
    return render_template('signup.html')

if __name__ == '__main__':
    # 외부 접속 허용 (본인 PC IP로 접속 가능)
    app.run(host='0.0.0.0', port=5000, debug=True)