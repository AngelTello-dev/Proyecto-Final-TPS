import os
import sqlite3
from flask import Flask, render_template, request, redirect, flash, session
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'database.db')


def crear_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT,
        precio REAL,
        stock INTEGER,
        aplica_2x1 INTEGER DEFAULT 0
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ventas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER,
        cantidad INTEGER,
        total REAL
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS usuarios(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        rol TEXT -- 'admin' o 'cliente'
    )
    ''')

    # Contraseñas protegidas de forma profesional.
    hash_admin = generate_password_hash("1234")
    hash_cliente = generate_password_hash("5678")

    cursor.execute("INSERT OR IGNORE INTO usuarios (username, password, rol) VALUES ('admin', ?, 'admin')",(hash_admin,))
    cursor.execute("INSERT OR IGNORE INTO usuarios (username, password, rol) VALUES ('cliente', ?, 'cliente')",(hash_cliente,))


    conn.commit()
    conn.close()

crear_db()
app = Flask(__name__)
app.secret_key = 'clave_secreta_para_mi_tienda'

@app.route('/')
def inicio():
    if 'username' not in session:
        return redirect('/login')
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE username = ?", (username,))
        usuario = cursor.fetchone()
        conn.close()

        if usuario and check_password_hash(usuario[2],password):
            session['user_id'] = usuario[0]
            session['username'] = usuario[1]
            session['rol'] = usuario[3]  # Guardamos si es admin o cliente
            flash(f"Bienvenido {username}", "success")
            return redirect('/')
        else:
            flash("Usuario o contraseña incorrectos", "danger")

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()  # Borra la sesión
    return redirect('/login')

@app.route('/productos')
def productos():
    if 'rol' not in session or session['rol'] != 'admin':
        flash("Acceso denegado. Solo administradores.", "danger")
        return redirect('/')
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM productos")
    productos = cursor.fetchall()
    conn.close()

    return render_template('productos.html', productos=productos)


# 1. Ruta para añadir cosas al carrito (la que te da el error 404)
@app.route('/agregar_al_carrito', methods=['POST'])
def agregar_al_carrito():
    if 'carrito' not in session:
        session['carrito'] = []

    try:
        cantidad = int(request.form.get('cantidad'))
        producto_id = int(request.form.get('producto_id'))
    except (ValueError, TypeError):
        flash("Por favor, ingresa un número válido.", "danger")
        return redirect('/ventas')

    if cantidad <= 0:
        flash("¡Error! La cantidad debe ser mayor a cero.", "warning")
        return redirect('/ventas')

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT nombre, precio, stock, aplica_2x1 FROM productos WHERE id = ?", (producto_id,))
    producto = cursor.fetchone()
    conn.close()

    if producto:
        nombre, precio, stock_disponible, aplica_2x1 = producto[0], producto[1], producto[2], producto[3]

        # --- VALIDACIÓN DE STOCK ---
        if cantidad > stock_disponible:
            flash(f"No hay suficiente stock de {nombre}. Disponible: {stock_disponible}", "danger")
            return redirect('/ventas')

        carrito = session['carrito']
        encontrado = False

        for item in carrito:
            if item['id'] == producto_id:
                # Verificar que la suma en el carrito no supere el inventario
                if (item['cantidad'] + cantidad) > stock_disponible:
                    flash(f"No puedes agregar más {nombre}, superarías el stock disponible.", "danger")
                    return redirect('/ventas')

                item['cantidad'] += cantidad

                # RECALCULAR SUBTOTAL CON 2X1 SI APLICA
                if aplica_2x1 == 1:
                    unidades_a_cobrar = item['cantidad'] - (item['cantidad'] // 2)
                    item['subtotal'] = unidades_a_cobrar * precio
                    total_sin_descuento = item['cantidad'] * precio
                    item['descuento'] = total_sin_descuento - item['subtotal']
                else:
                    item['subtotal'] = item['cantidad'] * precio
                    item['descuento'] = 0

                encontrado = True

                break

        if not encontrado:
            # CALCULAR SUBTOTAL PARA EL NUEVO ITEM CON 2X1 SI APLICA
            if aplica_2x1 == 1:
                unidades_a_cobrar = cantidad - (cantidad // 2)
                subtotal_inicial = unidades_a_cobrar * precio
                total_sin_descuento = cantidad * precio
                descuento_inicial = total_sin_descuento - subtotal_inicial
            else:
                subtotal_inicial = cantidad * precio
                descuento_inicial = 0

            carrito.append({
                'id': producto_id,
                'nombre': nombre,
                'precio': precio,
                'cantidad': cantidad,
                'subtotal': subtotal_inicial,
                'descuento': descuento_inicial
            })

        session['carrito'] = carrito
        session.modified = True # obliga a Flask a guardar los cambios.
        flash(f"Agregado: {nombre}", "success")

    return redirect('/ventas')


# 2. Ruta para vaciar el carrito
@app.route('/vaciar_carrito')
def vaciar_carrito():
    session.pop('carrito', None)
    return redirect('/ventas')


# 3. Ruta para cobrar lo que esta en el carrito
@app.route('/procesar_compra', methods=['POST'])
def procesar_compra():
    carrito = session.get('carrito', [])
    if not carrito:
        return redirect('/ventas')

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        for item in carrito:
            # Registrar cada venta
            cursor.execute("INSERT INTO ventas (producto_id, cantidad, total) VALUES (?, ?, ?)",
                           (item['id'], item['cantidad'], item['subtotal']))
            # Descontar del inventario
            cursor.execute("UPDATE productos SET stock = stock - ? WHERE id = ?",
                           (item['cantidad'], item['id']))

        conn.commit()
        session.pop('carrito', None)  # Limpiar carrito tras la venta
        flash("¡Venta completada con éxito!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "danger")
    finally:
        conn.close()

    return redirect('/ventas')

@app.route('/agregar_producto', methods=['POST'])
def agregar_producto():

    # candado de seguridad.
    if 'rol' not in session or session['rol'] != 'admin':
        flash("Acceso denegado. Solo administradores.", "danger")
        return redirect('/')

    nombre = request.form.get('nombre')

    # Capturamos el valor del Checkbox del 2x1.
    aplica_2x1 = 1 if request.form.get('aplica_2x1') else 0

    try:
        # Convierte y validamos que sean números
        precio = float(request.form.get('precio'))
        stock = int(request.form.get('stock'))
    except (ValueError, TypeError):
        flash("Error: El precio y el stock deben ser números validos.", "danger")
        return redirect('/productos')

    # --- VALIDACIONES DE NEGATIVOS O CERO ---
    if precio <= 0 or stock < 0:
        flash("Verificar los valres numéricos.", "warning")
        return redirect('/productos')

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO productos (nombre, precio, stock, aplica_2x1) VALUES (?, ?, ?, ?)",
                   (nombre, precio, stock, aplica_2x1))
    conn.commit()
    conn.close()
    flash(f"producto '{nombre}' agregado correctamente.", "success")
    return redirect('/productos')


@app.route('/eliminar_producto/<int:id>')
def eliminar_producto(id):

    if 'rol' not in session or session['rol'] != 'admin':
        flash("Acceso denegado. Solo administradores.", "danger")
        return redirect('/')

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Eliminamos le producto usando su ID único.
    cursor.execute("DELETE FROM productos WHERE id = ?",(id,))

    conn.commit()
    conn.close()

    # Mandamos un mensaje de confirmación.
    flash("Producto eliminado correctamente", "warning")
    return redirect('/productos')

@app.route('/editar_producto/<int:id>')
def editar_producto(id):

    if 'rol' not in session or session['rol'] != 'admin':
        flash("Acceso denegado. Solo administradores.", "danger")
        return redirect('/')

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, nombre, precio, stock, aplica_2x1 FROM productos WHERE id = ?",(id,))
    producto = cursor.fetchone()
    conn.close()
    return render_template('editar_producto.html', producto=producto)

@app.route('/actualizar_producto', methods=['POST'])
def actualizar_producto():

    if 'rol' not in session or session['rol'] != 'admin':
        flash("Acceso denegado. Solo administradores.", "danger")
        return redirect('/')

    id_prod = request.form.get('id')
    nombre = request.form.get('nombre')
    aplica_2x1 = 1 if request.form.get('aplica_2x1') else 0

    try:
        precio = float(request.form.get('precio'))
        stock = int(request.form.get('stock'))
    except (ValueError, TypeError):
        flash("Error en el formato de los datos.", "danger")
        return redirect('/productos')

    # Reutilizamos las validaciones
    if precio <= 0:
        flash("El precio actualizado debe ser mayor a cero.", "warning")
        return redirect(f'/editar_producto/{id_prod}')

    if stock < 0:
        flash("El sotck actualizado no puede ser negativo.", "warning")
        return redirect(f'/editar_producto/{id_prod}')

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE productos SET nombre = ?, precio = ?, stock = ?, aplica_2x1 = ? WHERE id = ?",
                   (nombre, precio, stock, aplica_2x1, id_prod))
    conn.commit()
    conn.close()
    flash("Producto actualizado con exito.", "success")
    return redirect('/productos')


@app.route('/ventas')
def ventas():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM productos")
    productos = cursor.fetchall()
    conn.close()

    return render_template('ventas.html', productos=productos)


# Historial de ventas.
@app.route('/historial')
def historial():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT ventas.id, productos.nombre, ventas.cantidad, ventas.total
    FROM ventas
    JOIN productos ON ventas.producto_id = productos.id
    ''')

    ventas = cursor.fetchall()

    # 🔥 SOLUCIÓN AL ERROR
    cursor.execute("SELECT SUM(total) FROM ventas")
    resultado = cursor.fetchone()

    total_general = resultado[0] if resultado[0] is not None else 0

    conn.close()

    return render_template('historial.html', ventas=ventas, total=total_general)

if __name__ == '__main__':
    app.run(debug=True) # inicio de la aplicacion de la pagina web.