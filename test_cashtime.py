#!/usr/bin/env python3
"""
Script de teste para a API Cashtime
"""
import os
import sys
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

# Adicionar o diretório atual ao path para importar os módulos
sys.path.append('.')

# Importar a aplicação Flask para contexto
from app import app
from cashtime_payments import create_cashtime_api

def test_cashtime_api():
    """Testa a API Cashtime com dados de exemplo"""
    print("🧪 Testando API Cashtime...")
    
    # Usar contexto da aplicação Flask
    with app.app_context():
        try:
            # Criar instância da API
            api = create_cashtime_api()
            print("✅ API Cashtime inicializada com sucesso")
            
            # Dados de teste
            test_data = {
                'name': 'João Silva Teste',
                'cpf': '12345678901',
                'phone': '11987654321',
                'amount': 83.40,
                'email': 'joao.teste@gmail.com'
            }
            
            print(f"📋 Dados de teste: {test_data}")
            
            # Tentar criar um pagamento PIX
            print("🔄 Criando pagamento PIX de teste...")
            result = api.create_pix_payment(test_data)
            
            print("✅ Pagamento criado com sucesso!")
            print(f"📄 Resultado: {result}")
            
            # Se temos um ID, testar verificação de status
            if result.get('id'):
                print(f"🔄 Testando verificação de status para ID: {result['id']}")
                status = api.check_payment_status(result['id'])
                print(f"📊 Status: {status}")
            
            return True
            
        except Exception as e:
            print(f"❌ Erro no teste: {str(e)}")
            return False

if __name__ == "__main__":
    success = test_cashtime_api()
    if success:
        print("\n🎉 Teste da API Cashtime concluído com sucesso!")
    else:
        print("\n💥 Teste da API Cashtime falhou!")
        sys.exit(1)