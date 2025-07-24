import os
import requests
import base64
from typing import Dict, Any, Optional
from flask import current_app
import logging

class CashtimePaymentsAPI:
    """
    Cashtime Payments API integration for PIX transactions
    Based on official Cashtime API documentation
    """
    # Official API endpoint from documentation
    API_URL = "https://api.cashtime.com.br/v1"
    
    def __init__(self, secret_key: str):
        """
        Initialize Cashtime API client
        
        Args:
            secret_key: Cashtime secret key for authentication
        """
        self.secret_key = secret_key
        self.access_token = None
        current_app.logger.info("Cashtime API inicializada")
    
    def _get_headers(self) -> Dict[str, str]:
        """
        Generate headers for API requests with x-authorization-key
        Following working Cashtime integration documentation
        """
        return {
            'Content-Type': 'application/json',
            'x-authorization-key': self.secret_key,
        }
    
    def authenticate_with_credentials(self, store_id: str, code: str) -> bool:
        """
        Authenticate using the credentials endpoint
        
        Args:
            store_id: Store ID for the credentials endpoint
            code: Authentication code
            
        Returns:
            True if authentication successful, False otherwise
        """
        try:
            url = f"{self.API_URL}/credentials/{store_id}"
            payload = {"code": code}
            
            current_app.logger.info(f"[CASHTIME] Autenticando com store_id: {store_id}")
            
            response = requests.post(url, json=payload, timeout=30)
            current_app.logger.info(f"[CASHTIME] Status da autenticação: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                if 'access_token' in result:
                    self.access_token = result['access_token']
                    current_app.logger.info("[CASHTIME] Autenticação bem-sucedida")
                    return True
                    
            current_app.logger.error(f"[CASHTIME] Erro na autenticação: {response.text}")
            return False
            
        except Exception as e:
            current_app.logger.error(f"[CASHTIME] Erro durante autenticação: {str(e)}")
            return False
    
    def _generate_random_email(self, name: str) -> str:
        """Generate a random email based on the name"""
        import random
        import string
        
        # Clean the name and create email
        clean_name = ''.join(c.lower() for c in name if c.isalnum())
        random_suffix = ''.join(random.choices(string.digits, k=4))
        
        domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com']
        domain = random.choice(domains)
        
        return f"{clean_name}{random_suffix}@{domain}"
    
    def _generate_random_phone(self) -> str:
        """Generate a random Brazilian phone number"""
        import random
        
        # Generate a Brazilian mobile number format: +55 11 9XXXX-XXXX
        area_codes = ['11', '21', '31', '41', '51', '61', '71', '81', '85', '62']
        area_code = random.choice(area_codes)
        
        # Mobile numbers start with 9
        number = f"9{random.randint(1000, 9999)}{random.randint(1000, 9999)}"
        
        return f"+55{area_code}{number}"
    
    def create_pix_payment(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a PIX payment request with Cashtime API
        
        Args:
            data: Payment data containing name, cpf, phone, amount, email
            
        Returns:
            Dict containing payment response data
        """
        try:
            current_app.logger.info(f"[CASHTIME] Criando pagamento PIX: {data}")
            
            # Validate required data
            required_fields = ['name', 'cpf', 'amount']
            for field in required_fields:
                if not data.get(field):
                    raise ValueError(f"Campo obrigatório ausente: {field}")
            
            # Clean and format CPF (remove dots and dashes)
            cpf = ''.join(filter(str.isdigit, str(data['cpf'])))
            if len(cpf) != 11:
                raise ValueError("CPF deve ter 11 dígitos")
            
            # Generate email if not provided
            email = data.get('email') or self._generate_random_email(data['name'])
            
            # Generate phone if not provided
            phone = data.get('phone') or self._generate_random_phone()
            
            # Format amount (ensure it's a float with 2 decimal places)
            amount = float(data['amount'])
            
            # Generate unique merchant reference
            import uuid
            merchant_ref = f"encceja_{uuid.uuid4().hex[:12]}"
            
            # Prepare payload following working Cashtime integration documentation
            amount_in_cents = int(amount * 100)  # Convert to cents
            
            payload = {
                'paymentMethod': 'pix',
                'customer': {
                    'name': data['name'],
                    'email': email,
                    'phone': phone,
                    'document': {
                        'number': cpf,
                        'type': 'cpf'
                    }
                },
                'items': [
                    {
                        'title': 'Taxa ENCCEJA 2025',
                        'description': f"Taxa de inscrição ENCCEJA 2025 - {data['name']}",
                        'unitPrice': amount_in_cents,
                        'quantity': 1,
                        'tangible': False  # Digital product
                    }
                ],
                'isInfoProducts': True,  # Digital products - no address needed
                'installments': 1,
                'installmentFee': 0,
                'postbackUrl': f"{current_app.config.get('BASE_URL', 'http://localhost:5000')}/webhook/cashtime",
                'ip': '127.0.0.1',
                'amount': amount_in_cents
            }
            
            current_app.logger.info(f"[CASHTIME] Payload preparado: {payload}")
            
            # Make request to Cashtime API
            response = requests.post(
                f"{self.API_URL}/transactions",
                json=payload,
                headers=self._get_headers(),
                timeout=30
            )
            
            current_app.logger.info(f"[CASHTIME] Status da resposta: {response.status_code}")
            current_app.logger.info(f"[CASHTIME] Resposta completa: {response.text}")
            
            if response.status_code == 201 or response.status_code == 200:
                response_data = response.json()
                current_app.logger.info(f"[CASHTIME] Pagamento criado com sucesso: {response_data}")
                
                # Extract PIX data from response following working format
                pix_data = response_data.get('pix', {})
                
                result = {
                    'success': True,
                    'id': response_data.get('id') or response_data.get('orderId'),
                    'status': response_data.get('status', 'pending'),
                    'amount': amount,
                    'currency': 'BRL',
                    'pixCode': pix_data.get('payload', ''),
                    'qrCodeImage': pix_data.get('encodedImage', ''),
                    'merchantRefNum': merchant_ref,
                    'description': f"Taxa ENCCEJA 2025 - {data['name']}",
                    'customer': {
                        'name': data['name'],
                        'email': email,
                        'phone': phone,
                        'document': cpf
                    }
                }
                
                return result
                
            else:
                error_msg = f"Erro na API Cashtime: {response.status_code} - {response.text}"
                current_app.logger.error(f"[CASHTIME] {error_msg}")
                raise Exception(error_msg)
                
        except Exception as e:
            current_app.logger.error(f"[CASHTIME] Erro ao criar pagamento: {str(e)}")
            raise e
    
    def check_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """
        Check the status of a payment transaction
        
        Args:
            payment_id: The transaction ID to check
            
        Returns:
            Dict containing payment status information
        """
        try:
            current_app.logger.info(f"[CASHTIME] Verificando status do pagamento: {payment_id}")
            
            # Make request to check payment status
            response = requests.get(
                f"{self.API_URL}/transactions/{payment_id}",
                headers=self._get_headers(),
                timeout=30
            )
            
            current_app.logger.info(f"[CASHTIME] Status check response: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                current_app.logger.info(f"[CASHTIME] Status obtido: {response_data}")
                
                # Extract order information from Cashtime response structure
                orders = response_data.get('orders', {})
                
                # Map Cashtime status to our standard format
                status_mapping = {
                    'pending': 'PENDING',
                    'waiting': 'PENDING',
                    'paid': 'PAID',
                    'completed': 'PAID',
                    'approved': 'PAID',
                    'confirmed': 'PAID',
                    'cancelled': 'CANCELLED',
                    'expired': 'EXPIRED',
                    'failed': 'FAILED'
                }
                
                original_status = orders.get('status', 'UNKNOWN')
                mapped_status = status_mapping.get(original_status.lower(), 'UNKNOWN')
                
                # Also check OrderTransportStatus if available
                transport_status = orders.get('OrderTransportStatus', {})
                if transport_status:
                    transport_status_value = transport_status.get('status', '').lower()
                    if transport_status_value in ['paid', 'approved', 'confirmed']:
                        mapped_status = 'PAID'
                
                return {
                    'id': payment_id,
                    'status': mapped_status,
                    'original_status': original_status,
                    'amount': orders.get('total'),
                    'paid_at': orders.get('updatedAt'),
                    'created_at': orders.get('createdAt'),
                    'orders': orders  # Incluir dados completos para acesso aos dados do cliente
                }
                
            else:
                error_msg = f"Erro ao verificar status: {response.status_code} - {response.text}"
                current_app.logger.error(f"[CASHTIME] {error_msg}")
                return {
                    'id': payment_id,
                    'status': 'ERROR',
                    'error': error_msg
                }
                
        except Exception as e:
            current_app.logger.error(f"[CASHTIME] Erro ao verificar status: {str(e)}")
            return {
                'id': payment_id,
                'status': 'ERROR',
                'error': str(e)
            }

def create_cashtime_api(secret_key: Optional[str] = None) -> CashtimePaymentsAPI:
    """Factory function to create CashtimePaymentsAPI instance"""
    if secret_key is None:
        secret_key = os.environ.get('CASHTIME_SECRET_KEY')
    
    if not secret_key:
        raise ValueError("CASHTIME_SECRET_KEY não encontrada nas variáveis de ambiente")
    
    return CashtimePaymentsAPI(secret_key)