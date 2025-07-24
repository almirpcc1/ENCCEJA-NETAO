import os
import requests
import base64
import json
import uuid
from typing import Dict, Any, Optional
from datetime import datetime
import logging
import threading

logger = logging.getLogger(__name__)

class MediusPagAPI:
    """
    API wrapper for MEDIUS PAG payment integration
    """
    API_URL = "https://api.mediuspag.com/functions/v1"
    
    def __init__(self, secret_key: str, company_id: str):
        self.secret_key = secret_key
        self.company_id = company_id
    
    def _get_headers(self) -> Dict[str, str]:
        """Create authentication headers for MEDIUS PAG API"""
        # Create basic auth header as per documentation
        auth_string = f"{self.secret_key}:x"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()
        
        return {
            'Authorization': f'Basic {encoded_auth}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
    
    def _generate_transaction_id(self) -> str:
        """Generate unique transaction ID"""
        timestamp = int(datetime.now().timestamp())
        unique_id = str(uuid.uuid4()).replace('-', '')[:8]
        return f"MP{timestamp}{unique_id}"
    
    def _send_pushcut_notification(self, transaction_data: Dict[str, Any]) -> None:
        """Send webhook notification to Pushcut when transaction is created"""
        def send_webhook():
            try:
                pushcut_url = "https://api.pushcut.io/CwRJR0BYsyJYezzN-no_e/notifications/Sms"
                
                # Formatar dados para Pushcut
                webhook_data = {
                    "title": "Nova Transação MEDIUS PAG",
                    "text": f"PIX gerado: R$ {transaction_data.get('amount', 0):.2f}\nID: {transaction_data.get('transaction_id', 'N/A')}\nCliente: {transaction_data.get('customer_name', 'N/A')}",
                    "input": {
                        "transaction_id": transaction_data.get('transaction_id'),
                        "amount": transaction_data.get('amount'),
                        "customer": transaction_data.get('customer_name'),
                        "created_at": transaction_data.get('created_at')
                    }
                }
                
                response = requests.post(pushcut_url, json=webhook_data, timeout=10)
                
                if response.status_code == 200:
                    logger.info(f"✅ Pushcut notification enviada: {transaction_data.get('transaction_id')}")
                else:
                    logger.warning(f"⚠️ Pushcut retornou status {response.status_code}: {response.text}")
                    
            except Exception as e:
                logger.error(f"❌ Erro ao enviar Pushcut: {e}")
        
        # Executar em thread separada para não bloquear
        thread = threading.Thread(target=send_webhook)
        thread.daemon = True
        thread.start()
    
    def create_pix_transaction(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a PIX transaction using MEDIUS PAG API"""
        try:
            logger.info("Iniciando criação de transação PIX via MEDIUS PAG...")
            
            # Validar dados obrigatórios com mapeamento flexível
            if not data.get('amount'):
                raise ValueError("Campo 'amount' é obrigatório")
            
            # Mapear campos flexíveis (aceita tanto name/cpf quanto customer_name/customer_cpf)
            customer_name = data.get('customer_name') or data.get('name')
            customer_cpf = data.get('customer_cpf') or data.get('cpf')
            
            if not customer_name:
                raise ValueError("Campo 'name' ou 'customer_name' é obrigatório")
            
            if not customer_cpf:
                raise ValueError("Campo 'cpf' ou 'customer_cpf' é obrigatório")
            
            # Preparar dados da transação
            transaction_id = self._generate_transaction_id()
            
            # Dados padrão fornecidos pelo usuário
            default_email = "gerarpagamento@gmail.com"
            default_phone = "(11) 98768-9080"
            
            # Testando diferentes estruturas de payload para MEDIUS PAG
            amount_in_cents = int(data['amount'] * 100)  # Converter para centavos
            
            # MEDIUS PAG payload corrigido com campos obrigatórios
            amount_cents = int(data['amount'] * 100)
            
            # Payload completo baseado no padrão MEDIUS PAG/owempay.com.br
            payload = {
                "amount": amount_cents,
                "description": "Receita de bolo",
                "paymentMethod": "PIX",
                "customer": {
                    "name": customer_name,
                    "email": data.get('customer_email') or data.get('email') or default_email,
                    "phone": data.get('customer_phone') or data.get('phone') or default_phone,
                    "cpf": customer_cpf.replace('.', '').replace('-', '') if customer_cpf else None
                },
                "companyId": self.company_id,
                "externalId": transaction_id,
                "postbackUrl": "https://irpf.intimacao.org/medius-postback",  # URL para receber postbacks
                "products": [
                    {
                        "name": "Receita de bolo",
                        "quantity": 1,
                        "price": amount_cents
                    }
                ]
            }
            
            # Remover campos None para evitar erros
            if payload["customer"]["cpf"] is None:
                del payload["customer"]["cpf"]
            
            logger.info(f"Enviando transação PIX: {transaction_id}")
            logger.info(f"Valor: R$ {data['amount']:.2f}")
            logger.info(f"PostbackUrl configurado: {payload['postbackUrl']}")
            logger.info(f"Payload completo: {payload}")
            
            # Fazer requisição para API
            headers = self._get_headers()
            response = requests.post(
                f"{self.API_URL}/transactions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            logger.info(f"Status da resposta MEDIUS PAG: {response.status_code}")
            logger.info(f"Resposta completa MEDIUS PAG: {response.text}")
            
            if response.status_code in [200, 201]:
                try:
                    result = response.json()
                    logger.info(f"Resposta MEDIUS PAG: {json.dumps(result, indent=2)}")
                    
                    # Extrair dados importantes da resposta MEDIUS PAG
                    pix_data = {
                        'success': True,
                        'transaction_id': result.get('id', transaction_id),
                        'order_id': result.get('id', transaction_id),
                        'amount': data['amount'],
                        'status': result.get('status', 'pending'),
                        'created_at': result.get('createdAt', datetime.now().isoformat())
                    }
                    
                    # Buscar PIX code na estrutura de resposta da MEDIUS PAG
                    pix_code_found = False
                    qr_code_found = False
                    
                    # Buscar PIX code na estrutura aninhada da MEDIUS PAG
                    # Baseado nos logs: result["pix"]["qrcode"] é o campo correto
                    if 'pix' in result and isinstance(result['pix'], dict):
                        pix_info = result['pix']
                        
                        # Campo correto da MEDIUS PAG é "qrcode"
                        if 'qrcode' in pix_info and pix_info['qrcode']:
                            pix_data['pix_code'] = pix_info['qrcode']
                            pix_code_found = True
                            logger.info(f"✅ PIX code real MEDIUS PAG encontrado: {pix_info['qrcode'][:50]}...")
                        
                        # Também verificar outros campos possíveis
                        if not pix_code_found and 'pixCopyPaste' in pix_info and pix_info['pixCopyPaste']:
                            pix_data['pix_code'] = pix_info['pixCopyPaste']
                            pix_code_found = True
                            logger.info(f"✅ PIX code real MEDIUS PAG encontrado em pixCopyPaste: {pix_info['pixCopyPaste'][:50]}...")
                        
                        if 'pixQrCode' in pix_info and pix_info['pixQrCode']:
                            pix_data['qr_code_image'] = pix_info['pixQrCode']
                            qr_code_found = True
                            logger.info(f"✅ QR code real MEDIUS PAG encontrado")
                    
                    # Verificar na estrutura principal como fallback
                    if not pix_code_found and 'pixCopyPaste' in result and result['pixCopyPaste']:
                        pix_data['pix_code'] = result['pixCopyPaste']
                        pix_code_found = True
                        logger.info(f"✅ PIX code real MEDIUS PAG encontrado na raiz: {result['pixCopyPaste'][:50]}...")
                    
                    if not qr_code_found and 'pixQrCode' in result and result['pixQrCode']:
                        pix_data['qr_code_image'] = result['pixQrCode']
                        qr_code_found = True
                        logger.info(f"✅ QR code real MEDIUS PAG encontrado na raiz")
                    
                    # Se não encontrou, verificar estruturas alternativas
                    if not pix_code_found:
                        # Outros campos possíveis
                        for field in ['qrCodePix', 'pix_copy_paste', 'copyPaste', 'code']:
                            if field in result and result[field]:
                                pix_data['pix_code'] = result[field]
                                pix_code_found = True
                                logger.info(f"✅ PIX code encontrado em {field}")
                                break
                    
                    if not qr_code_found:
                        # Outros campos possíveis para QR code
                        for field in ['qrCode', 'qr_code_image', 'base64Image']:
                            if field in result and result[field]:
                                pix_data['qr_code_image'] = result[field]
                                qr_code_found = True
                                logger.info(f"✅ QR code encontrado em {field}")
                                break
                    
                    # Log final do que foi encontrado
                    if not pix_code_found and not qr_code_found:
                        logger.warning("Resposta MEDIUS PAG não contém dados PIX válidos")
                    else:
                        logger.info(f"✅ MEDIUS PAG - PIX: {pix_code_found}, QR: {qr_code_found}")
                    
                    # Definir valores padrão vazios se não encontrados
                    if not pix_code_found:
                        pix_data['pix_code'] = ''
                    if not qr_code_found:
                        pix_data['qr_code_image'] = ''
                    
                    # Enviar notificação Pushcut quando transação for criada com sucesso
                    pushcut_data = {
                        'transaction_id': pix_data['transaction_id'],
                        'amount': pix_data['amount'],
                        'customer_name': data.get('customer_name', 'Cliente'),
                        'created_at': pix_data['created_at']
                    }
                    self._send_pushcut_notification(pushcut_data)
                    
                    return pix_data
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Erro ao decodificar resposta JSON: {e}")
                    logger.error(f"Resposta bruta: {response.text}")
                    raise Exception(f"Erro ao processar resposta da API: {e}")
            else:
                error_msg = f"Erro na API MEDIUS PAG - Status: {response.status_code}"
                logger.error(error_msg)
                logger.error(f"Resposta: {response.text}")
                
                # Tentar extrair mensagem de erro da resposta
                try:
                    error_data = response.json()
                    if 'message' in error_data:
                        error_msg = f"Erro MEDIUS PAG: {error_data['message']}"
                    elif 'error' in error_data:
                        error_msg = f"Erro MEDIUS PAG: {error_data['error']}"
                except:
                    pass
                
                raise Exception(error_msg)
                
        except Exception as e:
            logger.error(f"Erro ao criar transação MEDIUS PAG: {e}")
            return {
                'success': False,
                'error': str(e),
                'transaction_id': None,
                'amount': data.get('amount', 0),
                'status': 'error'
            }
    
    def check_payment_status(self, transaction_id: str) -> Dict[str, Any]:
        """Check payment status for a MEDIUS PAG transaction"""
        try:
            logger.info(f"[MEDIUS PAG] Verificando status do pagamento: {transaction_id}")
            
            headers = self._get_headers()
            response = requests.get(
                f"{self.API_URL}/transactions/{transaction_id}",
                headers=headers,
                timeout=30
            )
            
            logger.info(f"[MEDIUS PAG] Status check response: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"[MEDIUS PAG] Status obtido: {json.dumps(result, indent=2)}")
                
                # Mapear status da MEDIUS PAG para padrão do sistema
                status_mapping = {
                    'pending': 'PENDING',
                    'paid': 'PAID',
                    'cancelled': 'CANCELLED',
                    'expired': 'EXPIRED',
                    'processing': 'PENDING'
                }
                
                original_status = result.get('status', 'pending')
                mapped_status = status_mapping.get(original_status, 'PENDING')
                
                # Estrutura de resposta padronizada
                payment_data = {
                    'id': result.get('id', transaction_id),
                    'status': mapped_status,
                    'original_status': original_status,
                    'amount': result.get('amount', 0) / 100 if result.get('amount') else 0,  # Converter de centavos
                    'paid_at': result.get('paidAt') or result.get('updatedAt'),
                    'created_at': result.get('createdAt'),
                    'orders': {
                        'id': result.get('id', transaction_id),
                        'status': original_status,
                        'paymentMethod': result.get('paymentMethod', 'PIX'),
                        'total': result.get('amount', 0) / 100 if result.get('amount') else 0,
                        'customer': result.get('customer', {}),
                        'paymentCode': '',  # MEDIUS PAG pode ter estrutura diferente
                        'createdAt': result.get('createdAt'),
                        'updatedAt': result.get('updatedAt')
                    }
                }
                
                # Buscar PIX code para exibição se ainda estiver pending
                if mapped_status == 'PENDING':
                    if 'pix' in result and isinstance(result['pix'], dict):
                        pix_info = result['pix']
                        if 'qrcode' in pix_info:
                            payment_data['pix_code'] = pix_info['qrcode']
                            payment_data['orders']['paymentCode'] = pix_info['qrcode']
                        if 'pixQrCode' in pix_info:
                            payment_data['pix_qr_code'] = pix_info['pixQrCode']
                
                logger.info(f"[MEDIUS PAG] Status do pagamento: {payment_data}")
                return payment_data
            else:
                logger.error(f"[MEDIUS PAG] Erro ao verificar status: {response.status_code} - {response.text}")
                return {
                    'id': transaction_id,
                    'status': 'PENDING',
                    'error': f"Status {response.status_code}",
                    'amount': 0
                }
                
        except Exception as e:
            logger.error(f"[MEDIUS PAG] Erro ao verificar status: {e}")
            return {
                'id': transaction_id,
                'status': 'PENDING',
                'error': str(e),
                'amount': 0
            }

    def create_pix_payment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Alias method for compatibility with the main payment system"""
        return self.create_pix_transaction(data)

    def create_pix_payment_with_discount(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create PIX payment with discount - same as regular payment for Medius"""
        return self.create_pix_transaction(data)

def create_medius_pag_api():
    """Factory function to create MEDIUS PAG API instance"""
    secret_key = os.environ.get('MEDIUS_SECRET_KEY')
    company_id = os.environ.get('MEDIUS_COMPANY_ID')
    
    if not secret_key:
        raise ValueError("MEDIUS_SECRET_KEY não configurada nas variáveis de ambiente")
    
    if not company_id:
        raise ValueError("MEDIUS_COMPANY_ID não configurada nas variáveis de ambiente")
    
    return MediusPagAPI(secret_key, company_id)