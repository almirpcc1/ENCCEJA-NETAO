#!/usr/bin/env python3
"""
Teste rápido para obter token OAuth 2.0 da Cashtime
"""
import os
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

def test_token():
    print("🔑 Testando obtenção de token OAuth 2.0 da Cashtime...")
    
    secret_key = os.getenv('CASHTIME_SECRET_KEY')
    if not secret_key:
        print("❌ CASHTIME_SECRET_KEY não encontrada")
        return False
    
    print(f"🔐 Usando secret key: {secret_key[:20]}...")
    
    # URL do token
    token_url = "https://app.cashir.best/auth/token"
    
    # Preparar autenticação Basic Auth
    auth_string = f"{secret_key}:"
    auth_encoded = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        'Authorization': f'Basic {auth_encoded}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    data = {
        'grant_type': 'client_credentials'
    }
    
    print(f"📡 Fazendo requisição para: {token_url}")
    print(f"📋 Headers: {headers}")
    print(f"📋 Data: {data}")
    
    try:
        response = requests.post(
            token_url,
            headers=headers,
            data=data,
            timeout=15  # Timeout menor para teste
        )
        
        print(f"📊 Status: {response.status_code}")
        print(f"📄 Response: {response.text}")
        
        if response.status_code == 200:
            token_data = response.json()
            print(f"✅ Token obtido: {token_data.get('access_token', 'N/A')[:20]}...")
            return True
        else:
            print(f"❌ Erro: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"💥 Erro na requisição: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_token()
    if success:
        print("🎉 Teste de token bem-sucedido!")
    else:
        print("💔 Teste de token falhou!")