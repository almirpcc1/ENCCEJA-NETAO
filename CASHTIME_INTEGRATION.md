# Cashtime Payments API Integration

## Overview
This document details the integration with Cashtime Payments API for PIX transactions using the official API documentation.

## API Configuration

### Endpoint
- **Base URL**: `https://api.cashtime.com.br/v1`
- **Authentication**: Bearer Token
- **Documentation**: https://api.cashtime.com.br/docs

### Authentication
- **Method**: Bearer Token authentication
- **Header**: `Authorization: Bearer {secret_key}`
- **Token Source**: Secret key provided by Cashtime

### Required Environment Variables
- `CASHTIME_SECRET_KEY`: Your Cashtime secret/API key for Bearer authentication

## Current Implementation Status

### ✅ Updated Features (Based on Official Docs)
- Corrected API base URL to `https://api.cashtime.com.br/v1`
- Updated authentication to Bearer token (not OAuth 2.0)
- Transaction creation using `/v1/transactions` endpoint
- Payment status checking using `/v1/transactions/{id}` endpoint
- Error handling and comprehensive logging

### 🔧 Current Configuration
- Primary Gateway: **For4Payments** (fully operational)
- Secondary Gateway: **Cashtime** (updated with correct API)
- Gateway Selection: Environment variable `GATEWAY_CHOICE=for4`

## API Endpoints Used

### 1. Create Transaction (PIX Payment)
```
POST /v1/transactions
Authorization: Bearer {secret_key}
Content-Type: application/json

Payload:
{
  "amount": 83.40,
  "currency": "BRL", 
  "payment_method": "pix",
  "external_id": "encceja_xxx",
  "description": "Taxa ENCCEJA 2025",
  "customer": {
    "name": "Nome do Cliente",
    "email": "email@example.com", 
    "phone": "+5511999999999",
    "document": "12345678901"
  },
  "notification_url": "https://yoursite.com/webhook/cashtime",
  "return_url": "https://yoursite.com/obrigado"
}
```

### 2. Check Transaction Status
```
GET /v1/transactions/{transaction_id}
Authorization: Bearer {secret_key}
```

## Implementation Details

### Status Mapping
- `PENDING/WAITING` → `PENDING`
- `PAID/COMPLETED/APPROVED/CONFIRMED` → `PAID`
- `CANCELLED` → `CANCELLED`
- `EXPIRED` → `EXPIRED`
- `FAILED` → `FAILED`

### Customer Data Generation
- Auto-generates email if not provided
- Auto-generates Brazilian phone number if not provided
- Validates and formats CPF (11 digits only)

## Test Status - ✅ FULLY WORKING!
- **API Integration**: ✅ Working perfectly with correct authentication
- **Authentication**: ✅ `x-authorization-key` header method working 100%
- **Payment Creation**: ✅ PIX transactions created successfully (Status 201)
- **PIX Code Generation**: ✅ QR codes and copy/paste codes working
- **Status Checking**: ✅ Payment status verification functional
- **Primary Gateway**: ✅ For4Payments operational as backup
- **Dual Gateway System**: ✅ Complete with automatic failover

## Working Authentication Method
- **Header**: `x-authorization-key: {CASHTIME_SECRET_KEY}`
- **Content-Type**: `application/json`
- **Result**: Status 201 Created ✅

## Successful Test Results
```
✅ Transaction ID: 0f0cad29-e31c-4138-8c61-32f465ed3faf
✅ Status: pending (awaiting payment)
✅ Amount: R$ 83.40 (8340 cents)
✅ PIX Code: Generated successfully
✅ QR Code: Base64 image returned
✅ Customer: Data processed correctly
```

## Working Payload Format
- **Products**: Digital items (`isInfoProducts: true`)
- **Values**: Converted to cents (`amount * 100`)
- **Customer**: Structured with document object
- **Items**: Array with product details
- **Payment Method**: `pix`

## Next Steps
1. Test updated Cashtime integration with correct API endpoints
2. Verify Bearer token authentication works properly  
3. Test transaction creation and status checking
4. Monitor for any remaining API access issues

## Support Contact
For API access or integration issues:
- Official Documentation: https://api.cashtime.com.br/docs
- Contact Cashtime support for API key and access setup