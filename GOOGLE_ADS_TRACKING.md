# Google Ads Conversion Tracking - Configuração

## ✅ Status da Implementação
A integração do Google Ads foi configurada na página `/obrigado` com tracking de conversões automático.

## 🎯 Eventos de Conversão Configurados

### 1. Carregamento da Página de Agradecimento
- **Quando dispara**: Quando alguém acessa a página `/obrigado`
- **Valor**: R$ 143,10
- **Transaction ID**: `ENCCEJA-PAGELOAD-{timestamp}`
- **Objetivo**: Rastrear quantas pessoas chegam à página de pagamento

### 2. Confirmação de Pagamento
- **Quando dispara**: Quando o pagamento PIX é confirmado
- **Valor**: R$ 143,10
- **Transaction ID**: ID real da transação da API de pagamento
- **Objetivo**: Rastrear conversões reais (pagamentos aprovados)

## ⚙️ Configuração Necessária

### Passo 1: Obter o Conversion ID Real
1. Acesse sua conta do Google Ads
2. Vá em **Ferramentas e configurações** > **Conversões**
3. Crie uma nova conversão ou use uma existente
4. Copie o **Conversion ID** que aparece no formato: `AW-16865021402/ABC123XYZ`

### Passo 2: Atualizar o Código
Substitua `XYZ123ABC` pelo seu Conversion ID real em 3 locais no arquivo `templates/thank_you.html`:

```javascript
// Linha ~16 - Função sendGoogleAdsConversion
'send_to': 'AW-16865021402/SEU_CONVERSION_ID_AQUI',

// Linha ~600 - Evento no carregamento da página
'send_to': 'AW-16865021402/SEU_CONVERSION_ID_AQUI',

// Linha ~659 - Evento na confirmação de pagamento
'send_to': 'AW-16865021402/SEU_CONVERSION_ID_AQUI',
```

## 📊 Como Monitorar

### No Google Ads
1. Vá em **Conversões** no menu
2. Você verá as conversões sendo registradas
3. Use os filtros por **Transaction ID** para identificar tipos específicos:
   - `ENCCEJA-PAGELOAD-*`: Pessoas que chegaram à página
   - Outros IDs: Pagamentos realmente confirmados

### No Console do Navegador
- Eventos são logados automaticamente
- Procure por: `"Evento de conversão Google Ads enviado"`

## 🔧 Configurações do Evento

### Parâmetros Enviados
```javascript
{
    'send_to': 'AW-16865021402/SEU_CONVERSION_ID',
    'value': 143.10,           // Valor da taxa ENCCEJA
    'currency': 'BRL',         // Moeda brasileira
    'transaction_id': 'UNIQUE_ID', // ID único da transação
}
```

### Configurações Recomendadas no Google Ads
- **Categoria**: Compra/Venda
- **Valor**: Usar valores de conversão
- **Contagem**: Uma conversão por clique
- **Janela de conversão**: 30 dias
- **Janela de visualização**: 1 dia

## 🚀 Vantagens da Implementação

1. **Duplo Tracking**: Página + Pagamento confirmado
2. **IDs Únicos**: Cada conversão tem ID único para evitar duplicatas
3. **Valor Real**: R$ 143,10 (valor exato da taxa)
4. **Logs Detalhados**: Fácil debug via console
5. **Resistente a Erros**: Try/catch para evitar quebrar a página

## 📋 Próximos Passos

1. ✅ Substituir `XYZ123ABC` pelo Conversion ID real
2. ✅ Testar fazendo um pagamento de teste
3. ✅ Verificar no Google Ads se as conversões aparecem
4. ✅ Ajustar configurações de atribuição se necessário

## 🐛 Troubleshooting

**Conversões não aparecem?**
- Verifique se o Conversion ID está correto
- Aguarde até 3 horas para dados aparecerem
- Confira se não há bloqueadores de ads ativos

**Muitas conversões duplicadas?**
- Verifique se a configuração está como "Uma por clique"
- Transaction IDs únicos já previnem duplicatas

**Logs não aparecem no console?**
- Verifique se não há erros JavaScript na página
- Confirme se gtag está carregado corretamente