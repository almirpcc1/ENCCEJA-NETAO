import os
from novaerapayments import NovaEraPaymentsAPI, create_payment_api as create_novaera_api
from for4payments import For4PaymentsAPI, create_payment_api as create_for4_api
from cashtime_payments import CashtimePaymentsAPI, create_cashtime_api
from medius_payments import MediusPagAPI, create_medius_pag_api
from typing import Union

def get_payment_gateway() -> Union[NovaEraPaymentsAPI, For4PaymentsAPI, CashtimePaymentsAPI, MediusPagAPI]:
    """Factory function to create the appropriate payment gateway instance based on GATEWAY_CHOICE"""
    gateway_choice = os.environ.get("GATEWAY_CHOICE", "NOVAERA").upper()
    
    if gateway_choice == "NOVAERA":
        return create_novaera_api()
    elif gateway_choice == "FOR4":
        return create_for4_api()
    elif gateway_choice == "CASH" or gateway_choice == "CASHTIME":
        return create_cashtime_api()
    elif gateway_choice == "MEDIUS":
        return create_medius_pag_api()
    else:
        raise ValueError("GATEWAY_CHOICE must be either 'NOVAERA', 'FOR4', 'CASH', or 'MEDIUS'")
