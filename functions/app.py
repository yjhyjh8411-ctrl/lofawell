import os
import io
import uuid
import urllib.parse
# import pandas as pd # Moved inside function
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, make_response
from datetime import datetime
from werkzeug.utils import secure_filename
from flask_cors import CORS
from PIL import Image

app = Flask(__name__)
CORS(app) # Enable CORS for all routes
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024 # 32MB Upload Limit
app.secret_key = 'lofa_infra_final_perfect_2026'
app.config['SESSION_COOKIE_NAME'] = '__session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True 
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

_db = None
_bucket = None
_firebase_initialized = False

def init_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return

    import firebase_admin
    from firebase_admin import credentials, firestore

    try:
        if not firebase_admin._apps:
            if os.path.exists('serviceAccountKey.json'):
                cred = credentials.Certificate('serviceAccountKey.json')
                firebase_admin.initialize_app(cred, {
                    'storageBucket': 'lofa-43d38.firebasestorage.app',
                    'projectId': 'lofa-43d38'
                })
                print("Firebase initialized with serviceAccountKey.json")
            else:
                # Firebase App Hosting / Functions에서는 옵션 없이 호출하면 환경 변수(FIREBASE_CONFIG)를 통해 자동 설정됩니다.
                firebase_admin.initialize_app()
                print("Firebase initialized with Default Credentials")
        
        _firebase_initialized = True
        print("Firebase Cloud 연결 성공")
    except Exception as e:
        print(f"Firebase 연결 실패: {e}")

def get_db():
    global _db
    if _db is None:
        init_firebase()
        from firebase_admin import firestore
        _db = firestore.client()
    return _db

def get_bucket():
    global _bucket
    if _bucket is None:
        init_firebase()
        from firebase_admin import storage
        _bucket = storage.bucket()
    return _bucket

# --- [유틸리티 함수] ---
def upload_file_to_storage(file, user_id, user_name, apply_type):
    """Firebase Storage에 파일을 업로드하고 다운로드 URL을 반환합니다. 
    이미지 파일인 경우 자동으로 크기를 줄여서 업로드합니다."""
    if not file or file.filename == '':
        return ""
    
    try:
        now_date = datetime.now().strftime('%Y%m%d_%H%M%S')
        original_name = secure_filename(file.filename)
        ext = os.path.splitext(original_name)[1].lower()
        filename = f"{user_id}_{user_name}_{apply_type or 'unknown'}_{now_date}_{original_name}"
        
        bucket = get_bucket()
        
        # 파일 읽기
        file_content = file.read()
        content_type = file.content_type or 'application/octet-stream'

        # 이미지 압축 처리 (JPG, JPEG, PNG, WEBP 등)
        if ext in ['.jpg', '.jpeg', '.png', '.webp']:
            try:
                img = Image.open(io.BytesIO(file_content))
                
                # 이미지 모드 확인 및 변환 (RGBA -> RGB 등)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 이미지 크기 조정 (최대 너비/높이 1600px로 제한)
                max_size = 1600
                if img.width > max_size or img.height > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                
                # 압축된 이미지를 메모리 버퍼에 저장
                img_io = io.BytesIO()
                img.save(img_io, format='JPEG', quality=80, optimize=True)
                file_content = img_io.getvalue()
                content_type = 'image/jpeg'
                
                # 확장자가 바뀌었으므로 파일명도 .jpg로 조정
                if not filename.lower().endswith('.jpg') and not filename.lower().endswith('.jpeg'):
                    filename = os.path.splitext(filename)[0] + '.jpg'
            except Exception as img_err:
                print(f"Image compression failed, using original: {img_err}")
        
        # Firebase Storage용 다운로드 토큰 생성 (가장 확실한 다운로드 방법)
        access_token = str(uuid.uuid4())
        
        blob = bucket.blob(f"uploads/{filename}")
        blob.metadata = {"firebaseStorageDownloadTokens": access_token}
        
        # 파일 업로드
        blob.upload_from_string(file_content, content_type=content_type)
        
        # 메타데이터 업데이트 (토큰 적용)
        blob.patch()
        
        # 브라우저에서 바로 다운로드되도록 Content-Disposition 설정 (선택 사항)
        # blob.content_disposition = f'attachment; filename="{original_name}"'
        # blob.patch()

        # Firebase Storage 표준 다운로드 URL 형식 생성
        encoded_name = urllib.parse.quote(f"uploads/{filename}", safe='')
        public_url = f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/{encoded_name}?alt=media&token={access_token}"
        
        return public_url
    except Exception as e:
        print(f"Upload Error: {e}")
        return ""

# --- [인증 체크 미들웨어] ---
@app.before_request
def enforce_login():
    # 로그인이 필요하지 않은 경로들
    allowed_endpoints = ['index', 'login', 'signup_page', 'signup_process', 'static']
    
    # 세션에 user_id가 없고, 허용된 경로가 아닌 경우 로그인 페이지로 리다이렉트
    if request.endpoint not in allowed_endpoints and 'user_id' not in session:
        return redirect(url_for('index'))

# --- [보안 및 캐싱 방지 헤더 추가] ---
@app.after_request
def add_security_headers(response):
    # HTML 응답에 대해서만 캐싱을 강력하게 금지 (Cloudflare Edge Cache 방지)
    if response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
    return response

# --- [1. 로그인 및 세션] ---
@app.route('/')
def index():
    # 세션이 있으면 메인, 없으면 무조건 로그인 페이지
    if 'user_id' in session and session.get('user_id'):
        return render_template('main.html', user_name=session['user_name'])
    
    # 세션이 없는 경우 로그인 템플릿 반환
    # 로그아웃 후 뒤로가기 등을 방지하기 위해 응답 객체에 직접 캐시 헤더 추가
    resp = make_response(render_template('login.html'))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp

@app.route('/login', methods=['POST'])
def login():
    try:
        sid = str(request.form['employeeId']).strip()
        pw = str(request.form['password']).strip()
        
        db = get_db()
        user_ref = db.collection('users').document(sid).get()
        
        if user_ref.exists:
            u_info = user_ref.to_dict()
            stored_pw = str(u_info.get('비밀번호', '')).strip()
            
            if stored_pw == pw:
                session.permanent = True
                session.update({
                    'user_id': sid,
                    'user_name': u_info['이름'],
                    'user_dept': u_info.get('부서', ''),
                    'user_rank': u_info.get('직급', ''),
                    'user_join_date': u_info.get('입사일', ''),
                    'user_phone': u_info.get('전화번호', '')
                })
                return jsonify({"status": "success", "is_admin": sid == "admin"})
            else:
                return jsonify({"status": "error", "message": "비밀번호가 일치하지 않습니다."})
        
        return jsonify({"status": "error", "message": "등록되지 않은 사번입니다. 회원가입을 먼저 진행해 주세요."})
    except Exception as e:
        print(f"Login Error: {e}")
        return jsonify({"status": "error", "message": f"로그인 중 오류: {e}"})

# --- [2. 신청서 페이지 로드] ---
@app.route('/apply/<page>')
def apply_page(page):
    if 'user_id' not in session:
        return redirect(url_for('index'))

    edit_app_id = request.args.get('edit_app_id')
    data, edit_mode = None, False

    if edit_app_id:
        db = get_db()
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
            '입사일': session.get('user_join_date'),
            '전화번호': session.get('user_phone', '')
        }

    return render_template(f'{page}.html', user_name=session['user_name'], edit_mode=edit_mode, data=data)

# --- [3. 신청서 제출] ---
@app.route('/submit', methods=['GET', 'POST'])
@app.route('/edit_submit', methods=['POST'])
def handle_submit():
    print(f"Submit Request: {request.method} {request.path}")
    
    if request.method == 'GET':
        return jsonify({"status": "ok", "message": "Submit endpoint is reachable."})

    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "세션 만료. 다시 로그인해주세요."}), 401
    
    try:
        user_id = str(session.get('user_id'))
        user_name = str(session.get('user_name'))
        apply_type = request.form.get('type', '일반신청')
        
        print(f"Form Data: {request.form}")
        print(f"Files: {request.files}")

        file = request.files.get('attachment')
        file_url = request.form.get('old_filename', '')
        
        if file and file.filename != '':
            file_url = upload_file_to_storage(file, user_id, user_name, apply_type)

        # 모든 폼 데이터를 딕셔너리로 수집
        form_data_all = {}
        for key in request.form.keys():
            if key not in ['app_id', 'old_filename', 'type']:
                form_data_all[key] = request.form.get(key)

        amount_raw = str(request.form.get('amount', '0')).replace(',', '')
        try:
            amount_val = int(float(amount_raw))
        except (ValueError, TypeError):
            amount_val = 0
        
        detail_parts = [
            f"항목:{request.form.get('item_name', '')}",
            f"금융:{request.form.get('bank_name', '')}",
            f"본인부담:{request.form.get('self_pay', '0')}",
            f"지원구분:{request.form.get('target_name', '')}",
            f"내용:{request.form.get('detail_text', '')}"
        ]
        clean_detail = " / ".join(p for p in detail_parts if not p.endswith(':') and not p.endswith(':0'))
        if not clean_detail:
            clean_detail = request.form.get('detail_text', '')

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
            '첨부파일': file_url,
            'raw_data': form_data_all  # 모든 원본 필드 저장
        }

        db = get_db()
        db.collection('applications').document(app_id).set(new_data)
        
        return jsonify({"status": "success", "message": msg})

    except Exception as e:
        print(f"Submit Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- [4. 현황 및 관리자 페이지] ---
@app.route('/my_status')
def my_status():
    if 'user_id' not in session: return redirect(url_for('index'))
    
    uid = str(session.get('user_id'))
    print(f"DEBUG: Status query for user_id: {uid}")
    
    try:
        db = get_db()
        from google.cloud.firestore import FieldPath
        
        # Try different query styles to handle unicode field names safely
        try:
            # Style 1: Explicit FieldPath
            docs = db.collection('applications').where(FieldPath(['사번']), '==', uid).stream()
        except Exception as e1:
            print(f"DEBUG: Query Style 1 failed: {e1}")
            # Style 2: Plain string (original, might fail if encoding issues)
            docs = db.collection('applications').where('사번', '==', uid).stream()
        
        applications = []
        for doc in docs:
            d = doc.to_dict()
            if '신청일시' not in d: d['신청일시'] = ''
            applications.append(d)
            
        applications.sort(key=lambda x: x.get('신청일시', ''), reverse=True)
        return render_template('my_status.html', user_name=session['user_name'], applications=applications)
        
    except Exception as e:
        print(f"DEBUG: Status query fatal error: {e}")
        # Fallback: Fetch and filter in-memory if query still fails
        try:
            print("DEBUG: Executing fallback in-memory filter")
            all_docs = db.collection('applications').stream()
            applications = [d.to_dict() for d in all_docs if str(d.to_dict().get('사번')) == uid]
            applications.sort(key=lambda x: x.get('신청일시', ''), reverse=True)
            return render_template('my_status.html', user_name=session['user_name'], applications=applications)
        except Exception as e2:
            print(f"DEBUG: Fallback failed: {e2}")
            return jsonify({"status": "error", "message": f"데이터 로드 실패: {e}"}), 500

@app.route('/cancel_apply', methods=['POST'])
def cancel_apply():
    if 'user_id' not in session: return jsonify({"status": "error", "message": "세션 만료"}), 401
    
    app_id = request.form.get('app_id')
    action = request.form.get('action') # 'cancel' or 'delete'
    
    try:
        db = get_db()
        doc_ref = db.collection('applications').document(app_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return jsonify({"status": "error", "message": "해당 내역을 찾을 수 없습니다."})
        
        data = doc.to_dict()
        if str(data.get('사번')) != str(session.get('user_id')):
            return jsonify({"status": "error", "message": "권한이 없습니다."})
            
        if action == 'delete':
            doc_ref.delete()
            return jsonify({"status": "success", "message": "삭제되었습니다."})
        else:
            doc_ref.update({'상태': '취소'})
            return jsonify({"status": "success", "message": "취소되었습니다."})
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/admin')
def admin_dashboard():
    if session.get('user_id') != 'admin': return redirect(url_for('index'))
    
    cats = ['장학금지원', '경조비지원', '선진산업시찰', '주택지원', '복지연금', '의료비지원', '모성보호지원', '다자녀가정지원', '위로금지원', '생활복지지원']
    
    db = get_db()
    docs = db.collection('applications').stream()
    all_apps = [doc.to_dict() for doc in docs]
    
    # 최신순 정렬
    all_apps.sort(key=lambda x: x.get('신청일시', ''), reverse=True)
    
    summary = {}
    stats = {'total': len(all_apps), 'wait': 0, 'approve': 0, 'reject': 0}
    pending_list = []
    
    for app_item in all_apps:
        status = app_item.get('상태')
        if status == '대기': 
            stats['wait'] += 1
            pending_list.append(app_item)
        elif status == '승인': stats['approve'] += 1
        elif status == '반려': stats['reject'] += 1
        
        user_key = (app_item['사번'], app_item['성명'])
        if user_key not in summary:
            summary[user_key] = {cat: [] for cat in cats}
            summary[user_key]['사번'] = app_item['사번']
            summary[user_key]['성명'] = app_item['성명']
            summary[user_key]['부서'] = app_item.get('부서', '-')
            summary[user_key]['직급'] = app_item.get('직급', '-')
            summary[user_key]['입사일'] = app_item.get('입사일', '-')
            summary[user_key]['전화번호'] = app_item.get('전화번호', '-')
        
        cat = app_item['구분']
        if cat in cats:
            summary[user_key][cat].append({
                'app_id': app_item['app_id'],
                'amount': format(app_item.get('신청금액', 0), ','),
                'status': status,
                'apply_date': app_item['신청일시'],
                'attachment': app_item.get('첨부파일', ''), # summary에 명시적 포함
                'detail': app_item
            })

    return render_template('admin.html', 
                           summary=list(summary.values()), 
                           categories=cats, 
                           stats=stats, 
                           pending_list=pending_list,
                           user_name=session['user_name'])

@app.route('/admin_process', methods=['POST'])
def admin_process():
    if session.get('user_id') != 'admin': return jsonify({"status": "error"})
    
    app_id = request.form.get('app_id')
    status = request.form.get('status')
    reason = request.form.get('reason', '')
    
    db = get_db()
    db.collection('applications').document(app_id).update({
        '상태': status,
        '반려의견': reason
    })
    return jsonify({"status": "success"})

# --- [엑셀 다운로드 기능 개선] ---
@app.route('/download_excel')
def download_excel():
    if session.get('user_id') != 'admin': return redirect(url_for('index'))
    
    try:
        import pandas as pd
        db = get_db()
        docs = db.collection('applications').stream()
        all_apps = []
        for doc in docs:
            d = doc.to_dict()
            # 원본 데이터(raw_data)가 있으면 그것을 기반으로 정리
            row = {
                'ID': d.get('app_id'),
                '신청일시': d.get('신청일시'),
                '구분': d.get('구분'),
                '사번': d.get('사번'),
                '성명': d.get('성명'),
                '부서': d.get('부서'),
                '직급': d.get('직급'),
                '입사일': d.get('입사일'),
                '전화번호': d.get('전화번호'),
                '신청금액': d.get('신청금액'),
                '계좌번호': d.get('계좌번호'),
                '상태': d.get('상태'),
                '반려의견': d.get('반려의견'),
                '첨부파일': d.get('첨부파일')
            }
            # raw_data에 있는 추가 필드들도 병합 (중복 제외)
            if 'raw_data' in d and isinstance(d['raw_data'], dict):
                for k, v in d['raw_data'].items():
                    if k not in ['user_name', 'user_id', 'user_dept', 'position', 'joinDate', 'phone', 'amount', 'account', 'type']:
                        row[f"상세_{k}"] = v
            all_apps.append(row)
        
        if not all_apps:
            return "데이터가 없습니다."

        df = pd.DataFrame(all_apps)
        
        # 컬럼 순서 조정 (주요 정보 우선)
        main_cols = ['사번', '성명', '구분', '신청금액', '상태', '신청일시', '부서', '직급', '입사일', '전화번호', '계좌번호']
        cols = [c for c in main_cols if c in df.columns] + [c for c in df.columns if c not in main_cols]
        df = df[cols]
        
        # 엑셀 파일 생성 (메모리상에서)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='복지신청내역')
        output.seek(0)
        
        return send_file(
            output,
            as_attachment=True,
            download_name=f"LOFA_applications_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        return f"엑셀 다운로드 오류: {e}"

# --- [5. 회원가입 및 로그아웃] ---
@app.route('/signup_process', methods=['POST'])
def signup_process():
    sid = str(request.form.get('employeeId')).strip()
    pw = str(request.form.get('password')).strip()
    
    db = get_db()
    user_ref = db.collection('users').document(sid).get()
    
    if user_ref.exists:
        return jsonify({"status": "error", "message": "이미 등록된 사번입니다."})
    
    new_user = {
        '사번': sid,
        '비밀번호': pw,
        '이름': request.form.get('userName'),
        '직급': request.form.get('position'),
        '부서': request.form.get('department'),
        '입사일': request.form.get('joinDate'),
        '전화번호': request.form.get('phone')
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
    init_firebase()
    app.run(host='0.0.0.0', port=5000, debug=True)
