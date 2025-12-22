from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import or_

import csv
from flask import Response
from io import StringIO

from flask import session

app = Flask(__name__)
# 使用 SQLite，這會在你資料夾產生一個 campus.db 檔案
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///campus.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'any_long_random_string_here'
db = SQLAlchemy(app)

# --- 資料庫模型 (Database Models) ---

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    products = db.relationship('Product', backref='category', lazy=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(10), default='user') # 'admin' 或 'user'

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='Active')
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    # 關聯使用者
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id')) # 賣家
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id')) # 買家
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()
    # 自動建立測試帳號
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password='123', role='admin')
        user1 = User(username='user1', password='123', role='user')
        user2 = User(username='user2', password='123', role='user')
        db.session.add_all([admin, user1, user2])
    
    # 如果分類是空的，幫你加幾個進去
    if not Category.query.first():
        cats = [Category(name='資工系課本'), Category(name='通識教材'), Category(name='生活用品')]
        db.session.add_all(cats)
        db.session.commit()
        
    db.session.commit()



# --- 路由 (Routes) ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username'], 
                                 password=request.form['password']).first()
        if u:
            session['user_id'] = u.id
            session['role'] = u.role
            session['username'] = u.username
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/add', methods=['GET', 'POST'])
def add_product():
    if 'user_id' not in session: return redirect(url_for('login'))

    if request.method == 'POST':
        new_prod = Product(
            title=request.form['title'],
            price=request.form['price'],
            description=request.form['description'],
            category_id=request.form['category_id'],
            owner_id=session['user_id'] # 綁定當前登入者
        )
        db.session.add(new_prod)
        db.session.commit()
        return redirect(url_for('index'))
    
    categories = Category.query.all()
    return render_template('add.html', categories=categories)

@app.route('/my_items')
def my_items():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    user_id = session['user_id']
    # 找我賣的
    my_sales = Product.query.filter_by(owner_id=user_id).all()
    # 找我買的
    my_purchases = Product.query.filter_by(buyer_id=user_id).all()
    
    return render_template('my_items.html', sales=my_sales, purchases=my_purchases)

# --- 修改後的首頁路由 (支援權限分級 + 關鍵字搜尋) ---
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    role = session['role']
    query = request.args.get('q') # 取得搜尋關鍵字 (來自 URL 的 ?q=...)
    

    # 第一步：根據角色建立基礎查詢 (Base Query)
    if role == 'admin':
        # 管理員看所有資料
        base_stmt = Product.query
    else:
        # 訪客看「Active」或是「與自己有關」的資料
        base_stmt = Product.query.filter(
            or_(
                Product.status == 'Active',
                Product.owner_id == user_id,
                Product.buyer_id == user_id
            )
        )

    # 第二步：如果有搜尋關鍵字，再套用 LIKE 過濾
    if query:
        products = base_stmt.filter(
            or_(
                Product.title.like(f'%{query}%'),
                Product.description.like(f'%{query}%')
            )
        ).order_by(Product.created_at.desc()).all()
    else:
        # 沒有搜尋則直接回傳全部
        products = base_stmt.order_by(Product.created_at.desc()).all()
        
    return render_template('index.html', products=products, query=query)

# 修改後的刪除路由
@app.route('/delete/<int:id>')
def delete_product(id):
    if 'role' in session and session['role'] == 'admin': # 權限保護
        prod = Product.query.get_or_404(id)
        db.session.delete(prod)
        db.session.commit()
    return redirect(url_for('index')) # 刪除後導回首頁

# --- 新增編輯路由 ---
@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_product(id):
    prod = Product.query.get_or_404(id)
    
    if request.method == 'POST':
        # 更新資料庫欄位
        prod.title = request.form['title']
        prod.price = request.form['price']
        prod.description = request.form['description']
        prod.category_id = request.form['category_id']
        
        db.session.commit() # 提交更改
        return redirect(url_for('index'))
    
    categories = Category.query.all()
    return render_template('edit.html', product=prod, categories=categories)

@app.route('/buy/<int:id>')  # 這裡必須是 <int:id>
def buy_product(id):
    if 'user_id' not in session: 
        return redirect(url_for('login'))
    if 'user_id' not in session or session['role'] == 'admin':
        # 如果是管理員，直接導回首頁，不給買
        return redirect(url_for('index'))
    
    prod = Product.query.get_or_404(id)
    
    # 檢查邏輯：必須是 Active 且 買家不能是賣家本人
    if prod.status == 'Active' and prod.owner_id != session['user_id']:
        prod.status = 'Sold'
        prod.buyer_id = session['user_id']
        db.session.commit()
        print(f"DEBUG: Product {id} bought by {session['username']}") # 加入這行看後台有沒有跑
    
    return redirect(url_for('index'))

@app.route('/export')
def export_csv():
    # 取得所有商品
    prods = Product.query.all()
    
    # 使用 StringIO 建立記憶體內的 CSV 檔案
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'name', 'price', 'category', 'status']) # 標頭
    
    for p in prods:
        cw.writerow([p.id, p.title, p.price, p.category.name, p.status])
    
    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=books_report.csv"}
    )
    

if __name__ == '__main__':
    app.run(debug=True)