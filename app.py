import oracledb
import os
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": "*"}})

def get_connection():
    try:
        connection = oracledb.connect(
            user=os.environ.get("DB_USER"),
            password=os.environ.get("DB_PASSWORD"),
            dsn=os.environ.get("DB_DSN")
        )
        return connection
    except Exception as e:
        print(f"Erro ao conectar ao banco de dados: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/usuarios', methods=['GET'])
def listar_usuarios():
    conn = get_connection()
    if not conn:
        return jsonify({"erro": "Erro de conexão"}), 500
    
    try:
        cursor = conn.cursor()
        query = """
            SELECT 
                u.ID, 
                u.NOME, 
                u.SALDO,
                (SELECT TIPO FROM INSCRICOES WHERE USUARIO_ID = u.ID AND ROWNUM = 1) as TIPO,
                (SELECT COUNT(*) FROM INSCRICOES WHERE USUARIO_ID = u.ID AND STATUS = 'PRESENT') as PRESENCAS
            FROM USUARIOS u
            ORDER BY u.ID
        """
        cursor.execute(query)
        
        usuarios = []
        for row in cursor.fetchall():
            usuarios.append({
                "id": row[0],
                "nome": row[1],
                "saldo": f"{row[2]:.2f}",
                "tipo": row[3] if row[3] else "NORMAL",
                "presencas": row[4]
            })
        return jsonify(usuarios)
    finally:
        conn.close()

@app.route('/reset', methods=['POST'])
def resetar_dados():
    conn = get_connection()
    if not conn:
        return jsonify({"erro": "Erro de conexão"}), 500
    
    try:
        cursor = conn.cursor()
        # 1. Limpa a tabela de logs
        cursor.execute("DELETE FROM LOG_AUDITORIA")
        # 2. Volta o saldo de todos os usuários para um valor base (ex: 100)
        cursor.execute("UPDATE USUARIOS SET SALDO = 100")
        
        conn.commit()
        return jsonify({"status": "sucesso", "message": "Dados resetados com sucesso!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "erro", "message": str(e)}), 500
    finally:
        conn.close()

@app.route('/distribuir', methods=['POST'])
def distribuir_cashback():
    conn = get_connection()
    if not conn:
        return jsonify({"erro": "Erro de conexão com o banco"}), 500
    
    try:
        cursor = conn.cursor()
        
        plsql_block = """
        DECLARE
            CURSOR c_premiacao IS
                SELECT i.ID, u.ID as user_id, i.VALOR_PAGO, i.TIPO
                FROM USUARIOS u
                JOIN INSCRICOES i ON u.ID = i.USUARIO_ID
                WHERE i.STATUS = 'PRESENT';
            
            v_total_presencas NUMBER;
            v_percentual NUMBER;
            v_cashback NUMBER;
        BEGIN
            FOR reg IN c_premiacao LOOP
                -- Subquery para contar presenças totais (Critério > 3)
                SELECT COUNT(*) INTO v_total_presencas 
                FROM INSCRICOES 
                WHERE USUARIO_ID = reg.user_id AND STATUS = 'PRESENT';

                -- Lógica de Escalonamento
                IF v_total_presencas > 3 THEN
                    v_percentual := 0.25;
                ELSIF reg.TIPO = 'VIP' THEN
                    v_percentual := 0.20;
                ELSE
                    v_percentual := 0.10;
                END IF;

                v_cashback := reg.VALOR_PAGO * v_percentual;

                -- Atualização e Log
                UPDATE USUARIOS SET SALDO = SALDO + v_cashback WHERE ID = reg.user_id;
                
                INSERT INTO LOG_AUDITORIA (INSCRICAO_ID, MOTIVO, DATA)
                VALUES (reg.ID, 'CASHBACK ' || (v_percentual*100) || '% APLICADO', SYSDATE);
            END LOOP;
            
            COMMIT;
        END;
        """
        
        cursor.execute(plsql_block)
        return jsonify({"status": "sucesso", "message": "Processamento de cashback concluído!"})
    
    except oracledb.DatabaseError as e:
        error_obj, = e.args
        return jsonify({"status": "erro", "message": f"Erro Oracle {error_obj.code}: {error_obj.message}"}), 500
    except Exception as e:
        return jsonify({"status": "erro", "message": str(e)}), 500
    finally:
        conn.close()

if __name__ == '__main__':
    app.run(debug=True)