// ============================================================
// APIM AI Gateway
// ============================================================
// Configures an existing APIM instance as an AI gateway that:
//   1. Exposes the ACA-hosted agents (MAF, LangGraph) under a stable
//      /agents/{maf|langgraph}/* surface for registration as Foundry assets.
//   2. Exposes an Azure-OpenAI-compatible surface (/openai) that wraps
//      Foundry with managed-identity auth + token-limit + emit-token-metric.
//
// APIM itself is created by compute-layer.bicep (AVM); this module attaches
// backends, APIs, policies, logger and subscription on top.
// ============================================================

targetScope = 'resourceGroup'

@description('Name of the existing APIM instance (created by the compute layer).')
param apimName string

@description('Foundry AI Services account name (used to build the OpenAI backend URL).')
param aiFoundryAccountName string

@description('MAF agent container FQDN. Empty disables the MAF route.')
param mafAgentFqdn string = ''

@description('LangGraph agent container FQDN. Empty disables the LangGraph route.')
param langGraphAgentFqdn string = ''

@description('Application Insights resource ID for the APIM logger.')
param applicationInsightsResourceId string

@description('Application Insights instrumentation key (from applicationInsightsResourceId).')
@secure()
param applicationInsightsInstrumentationKey string

@description('Azure OpenAI API version to import (OpenAPI spec).')
param openAiApiVersion string = '2024-10-21'

@description('Token-per-minute limit enforced by APIM on the /openai surface.')
param tokenLimitTpm int = 100000

@description('Display name for the agents Foundry product (the package registered in Foundry connections).')
param agentsProductName string = 'foundry-agents'

@description('Optional audience for AAD token validation on /agents. When non-empty, the /agents policy requires a valid Entra ID token with this audience (e.g. the Foundry project app id or a custom API app registration).')
param agentsJwtAudience string = ''

@description('Optional Entra tenant ID for AAD token validation on /agents. Defaults to the subscription tenant.')
param agentsJwtTenantId string = tenant().tenantId

@description('Optional Key Vault name. When set, the module writes apim-openai-sub-key and apim-agents-sub-key as secrets into this vault.')
param keyVaultName string = ''

// ============================================================
// Existing references
// ============================================================
resource apim 'Microsoft.ApiManagement/service@2024-06-01-preview' existing = {
  name: apimName
}

// ============================================================
// Logger (Application Insights)
// ============================================================
resource appInsightsLogger 'Microsoft.ApiManagement/service/loggers@2024-06-01-preview' = {
  parent: apim
  name: 'appinsights-logger'
  properties: {
    loggerType: 'applicationInsights'
    description: 'Application Insights logger for the AI gateway.'
    resourceId: applicationInsightsResourceId
    credentials: {
      instrumentationKey: applicationInsightsInstrumentationKey
    }
  }
}

// ============================================================
// Backends
// ============================================================

// Foundry (Azure OpenAI surface). Managed-identity circuit breaker keeps the
// backend healthy under 429 bursts.
resource foundryBackend 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = {
  parent: apim
  name: 'foundry-openai'
  properties: {
    description: 'Foundry AI Services (Azure OpenAI compatible endpoint).'
    url: 'https://${aiFoundryAccountName}.openai.azure.com/openai'
    protocol: 'http'
    circuitBreaker: {
      rules: [
        {
          name: 'openai-breaker'
          failureCondition: {
            count: 5
            errorReasons: [ 'Server errors' ]
            interval: 'PT1M'
            statusCodeRanges: [
              {
                min: 429
                max: 429
              }
              {
                min: 500
                max: 599
              }
            ]
          }
          tripDuration: 'PT30S'
          acceptRetryAfter: true
        }
      ]
    }
  }
}

resource mafBackend 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = if (!empty(mafAgentFqdn)) {
  parent: apim
  name: 'maf-agent'
  properties: {
    description: 'MAF agent container app.'
    url: 'https://${mafAgentFqdn}'
    protocol: 'http'
  }
}

resource langGraphBackend 'Microsoft.ApiManagement/service/backends@2024-06-01-preview' = if (!empty(langGraphAgentFqdn)) {
  parent: apim
  name: 'langgraph-agent'
  properties: {
    description: 'LangGraph agent container app.'
    url: 'https://${langGraphAgentFqdn}'
    protocol: 'http'
  }
}

// ============================================================
// APIs
// ============================================================

// Azure OpenAI API (imported from the public OpenAPI spec).
resource openAiApi 'Microsoft.ApiManagement/service/apis@2024-06-01-preview' = {
  parent: apim
  name: 'azure-openai'
  properties: {
    displayName: 'Azure OpenAI (via Foundry)'
    description: 'Azure OpenAI compatible surface with MI auth, token-limit and token metrics.'
    path: 'openai'
    protocols: [ 'https' ]
    subscriptionRequired: true
    format: 'openapi-link'
    value: 'https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/specification/cognitiveservices/data-plane/AzureOpenAI/inference/stable/${openAiApiVersion}/inference.json'
  }
}

resource openAiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-06-01-preview' = {
  parent: openAiApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: replace(loadTextContent('policies/azure-openai-api.xml'), '__TPM__', string(tokenLimitTpm))
  }
  dependsOn: [
    foundryBackend
  ]
}

resource openAiDiagnostic 'Microsoft.ApiManagement/service/apis/diagnostics@2024-06-01-preview' = {
  parent: openAiApi
  name: 'applicationinsights'
  properties: {
    alwaysLog: 'allErrors'
    loggerId: appInsightsLogger.id
    sampling: {
      samplingType: 'fixed'
      percentage: 100
    }
    logClientIp: false
  }
}

// Agents API — fronts the ACA container apps.
resource agentsApi 'Microsoft.ApiManagement/service/apis@2024-06-01-preview' = if (!empty(mafAgentFqdn) || !empty(langGraphAgentFqdn)) {
  parent: apim
  name: 'agents'
  properties: {
    displayName: 'Foundry Hosted Agents (MAF + LangGraph)'
    description: 'Path-routed ingress for externally-hosted agents running on Azure Container Apps. Registered as Foundry assets.'
    path: 'agents'
    protocols: [ 'https' ]
    subscriptionRequired: true
  }
}

// Typed operations matching the Azure Agent Server surface. We declare them for
// both subroutes so Foundry can register operation-specific connections and APIM
// emits per-operation metrics. The policy handles backend dispatch from the path.
var agentSubroutes = filter([
  { key: 'maf', hasFqdn: !empty(mafAgentFqdn) }
  { key: 'langgraph', hasFqdn: !empty(langGraphAgentFqdn) }
], item => item.hasFqdn)

@batchSize(1)
resource agentsResponsesCreate 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = [for sub in agentSubroutes: if (!empty(mafAgentFqdn) || !empty(langGraphAgentFqdn)) {
  parent: agentsApi
  name: '${sub.key}-responses-create'
  properties: {
    displayName: '${sub.key}: Create response'
    method: 'POST'
    urlTemplate: '/${sub.key}/responses'
    templateParameters: []
    responses: []
  }
}]

@batchSize(1)
resource agentsResponsesGet 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = [for sub in agentSubroutes: if (!empty(mafAgentFqdn) || !empty(langGraphAgentFqdn)) {
  parent: agentsApi
  name: '${sub.key}-responses-get'
  properties: {
    displayName: '${sub.key}: Get response'
    method: 'GET'
    urlTemplate: '/${sub.key}/responses/{responseId}'
    templateParameters: [
      { name: 'responseId', type: 'string', required: true, description: 'Response identifier.' }
    ]
    responses: []
  }
}]

@batchSize(1)
resource agentsResponsesCancel 'Microsoft.ApiManagement/service/apis/operations@2024-06-01-preview' = [for sub in agentSubroutes: if (!empty(mafAgentFqdn) || !empty(langGraphAgentFqdn)) {
  parent: agentsApi
  name: '${sub.key}-responses-cancel'
  properties: {
    displayName: '${sub.key}: Cancel response'
    method: 'POST'
    urlTemplate: '/${sub.key}/responses/{responseId}/cancel'
    templateParameters: [
      { name: 'responseId', type: 'string', required: true, description: 'Response identifier.' }
    ]
    responses: []
  }
}]

// Optional AAD token validation for /agents. Injected into the policy at build time.
var jwtPolicyFragment = empty(agentsJwtAudience) ? '' : '<validate-azure-ad-token tenant-id="${agentsJwtTenantId}" header-name="Authorization" failed-validation-httpcode="401" failed-validation-error-message="Invalid or missing Entra ID token."><audiences><audience>${agentsJwtAudience}</audience></audiences></validate-azure-ad-token>'

resource agentsPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-06-01-preview' = if (!empty(mafAgentFqdn) || !empty(langGraphAgentFqdn)) {
  parent: agentsApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: replace(loadTextContent('policies/agents-api.xml'), '<!-- __JWT_VALIDATION__ -->', jwtPolicyFragment)
  }
  dependsOn: [
    mafBackend
    langGraphBackend
  ]
}

resource agentsDiagnostic 'Microsoft.ApiManagement/service/apis/diagnostics@2024-06-01-preview' = if (!empty(mafAgentFqdn) || !empty(langGraphAgentFqdn)) {
  parent: agentsApi
  name: 'applicationinsights'
  properties: {
    alwaysLog: 'allErrors'
    loggerId: appInsightsLogger.id
    sampling: {
      samplingType: 'fixed'
      percentage: 100
    }
    logClientIp: false
  }
}

// ============================================================
// Product + subscription (for Foundry to call /agents/*)
// ============================================================
resource agentsProduct 'Microsoft.ApiManagement/service/products@2024-06-01-preview' = if (!empty(mafAgentFqdn) || !empty(langGraphAgentFqdn)) {
  parent: apim
  name: agentsProductName
  properties: {
    displayName: 'Foundry Agents'
    description: 'Product for registering ACA-hosted agents as Foundry assets.'
    subscriptionRequired: true
    approvalRequired: false
    state: 'published'
  }
}

resource agentsProductApi 'Microsoft.ApiManagement/service/products/apiLinks@2024-06-01-preview' = if (!empty(mafAgentFqdn) || !empty(langGraphAgentFqdn)) {
  parent: agentsProduct
  name: 'agents-api-link'
  properties: {
    apiId: agentsApi.id
  }
}

resource openAiProduct 'Microsoft.ApiManagement/service/products@2024-06-01-preview' = {
  parent: apim
  name: 'foundry-openai'
  properties: {
    displayName: 'Foundry OpenAI Gateway'
    description: 'Azure OpenAI surface with MI auth and token governance.'
    subscriptionRequired: true
    approvalRequired: false
    state: 'published'
  }
}

resource openAiProductApi 'Microsoft.ApiManagement/service/products/apiLinks@2024-06-01-preview' = {
  parent: openAiProduct
  name: 'openai-api-link'
  properties: {
    apiId: openAiApi.id
  }
}

// A stable subscription for each product so the outputs are deterministic.
resource agentsSubscription 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' = if (!empty(mafAgentFqdn) || !empty(langGraphAgentFqdn)) {
  parent: apim
  name: 'foundry-agents-sub'
  properties: {
    displayName: 'Foundry Agents subscription'
    scope: agentsProduct.id
    state: 'active'
  }
}

resource openAiSubscription 'Microsoft.ApiManagement/service/subscriptions@2024-06-01-preview' = {
  parent: apim
  name: 'foundry-openai-sub'
  properties: {
    displayName: 'Foundry OpenAI subscription'
    scope: openAiProduct.id
    state: 'active'
  }
}

// ============================================================
// Optional: persist subscription keys to Key Vault.
// Lets ACA container apps consume them via secretRef without manual key rotation.
// ============================================================
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = if (!empty(keyVaultName)) {
  name: keyVaultName
}

resource openAiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(keyVaultName)) {
  parent: keyVault
  name: 'apim-openai-sub-key'
  properties: {
    value: openAiSubscription.listSecrets().primaryKey
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

resource agentsKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(keyVaultName) && (!empty(mafAgentFqdn) || !empty(langGraphAgentFqdn))) {
  parent: keyVault
  name: 'apim-agents-sub-key'
  properties: {
    value: agentsSubscription!.listSecrets().primaryKey
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

// ============================================================
// Outputs
// ============================================================
@description('Base URL of the APIM gateway.')
output gatewayUrl string = 'https://${apim.properties.hostnameConfigurations[0].hostName}'

@description('Full URL to register in Foundry for the MAF agent.')
output mafAgentApimUrl string = !empty(mafAgentFqdn) ? 'https://${apim.properties.hostnameConfigurations[0].hostName}/agents/maf' : ''

@description('Full URL to register in Foundry for the LangGraph agent.')
output langGraphAgentApimUrl string = !empty(langGraphAgentFqdn) ? 'https://${apim.properties.hostnameConfigurations[0].hostName}/agents/langgraph' : ''

@description('Azure OpenAI surface URL (for container apps and external callers).')
output openAiGatewayUrl string = 'https://${apim.properties.hostnameConfigurations[0].hostName}/openai'

@description('Resource ID of the agents subscription (used to fetch the subscription key).')
output agentsSubscriptionResourceId string = !empty(mafAgentFqdn) || !empty(langGraphAgentFqdn) ? agentsSubscription.id : ''

@description('Resource ID of the OpenAI subscription (used to fetch the subscription key).')
output openAiSubscriptionResourceId string = openAiSubscription.id

@description('Name of the KV secret holding the OpenAI APIM subscription key. Empty when keyVaultName is not set.')
output openAiKeySecretName string = !empty(keyVaultName) ? openAiKeySecret.name : ''

@description('Name of the KV secret holding the agents APIM subscription key. Empty when keyVaultName is not set or no agents are deployed.')
output agentsKeySecretName string = !empty(keyVaultName) && (!empty(mafAgentFqdn) || !empty(langGraphAgentFqdn)) ? agentsKeySecret.name : ''
