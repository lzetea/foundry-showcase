// ============================================================
// Microsoft Foundry — agent observability demo
// Subscription-scoped deployment:
//   1) Resource group
//   2) AI Foundry account + project + (optional) capability host for hosted agents
//      using avm/res/cognitive-services/account
//   3) Optional ACA + APIM + Cosmos + Key Vault compute layer
//      using AVM modules for every peripheral resource
//
// This template is intentionally hybrid: AVM covers everything that has a
// published AVM module; the Foundry project / capabilityHost / project
// connections are still native child resources because AVM does not publish
// a cognitive-services/account/project module.
// ============================================================

targetScope = 'subscription'

@description('Azure region for the resource group and all control-plane resources.')
param location string

@description('Location where Foundry model deployments are created. Defaults to the primary location.')
param aiDeploymentsLocation string = location

@description('Logical environment name, also used as the azd-env-name tag.')
@minLength(1)
@maxLength(24)
param environmentName string

@description('Name of the resource group to deploy into. Created if missing.')
@minLength(1)
@maxLength(90)
param resourceGroupName string

@description('Object ID of the deploying user / service principal. azd sets AZURE_PRINCIPAL_ID automatically.')
param principalId string

@description('Principal type of the deploying identity.')
@allowed([ 'User', 'ServicePrincipal' ])
param principalType string = 'User'

@description('Optional explicit name for the AI Foundry account. Auto-generated when empty.')
param aiFoundryResourceName string = ''

@description('Optional explicit name for the AI Foundry project. Auto-generated when empty.')
param aiFoundryProjectName string = ''

@description('Model deployment name passed to hosted agents. Must exist in aiProjectDeployments.')
param modelDeploymentName string = 'gpt-5'

@description('Model deployments. Defaults to a single gpt-5 GlobalStandard deployment. Override to deploy additional or different models.')
param aiProjectDeployments array = [
  {
    name: 'gpt-5'
    model: {
      format: 'OpenAI'
      name: 'gpt-5'
      version: '2025-08-07'
    }
    sku: {
      name: 'GlobalStandard'
      capacity: 10
    }
  }
]

@description('Create Log Analytics + Application Insights.')
param enableMonitoring bool = true

@description('Create the Foundry capability host and grant hosted-agent RBAC.')
param enableHostedAgents bool = false

@description('Deploy the ACA + Cosmos + Key Vault + (optional) APIM compute layer.')
param enableComputeLayer bool = false

@description('Deploy an Azure AI Search service and connect it to the Foundry project (Foundry IQ / Agent Knowledge).')
param enableAiSearch bool = true

@description('SKU for the Azure AI Search service.')
@allowed([
  'free'
  'basic'
  'standard'
  'standard2'
  'standard3'
])
param aiSearchSku string = 'standard'

@description('MAF agent container image reference. Empty skips the MAF container app.')
param mafContainerImage string = ''

@description('LangGraph agent container image reference. Empty skips the LangGraph container app.')
param langGraphContainerImage string = ''

@description('Publisher email for APIM. Empty skips APIM.')
param apimPublisherEmail string = ''

@description('Expected JWT audience for /agents API. Empty disables JWT validation (open for PoC).')
param apimAgentsJwtAudience string = ''

@description('Entra tenant ID used by JWT validation on /agents. Defaults to current tenant.')
param apimAgentsJwtTenantId string = tenant().tenantId

@description('Persist APIM subscription keys to Key Vault for downstream consumers.')
param apimSecretsToKeyVault bool = true

@description('Tokens-per-minute limit for the Azure OpenAI API behind APIM.')
param apimTokenLimitTpm int = 100000

@description('Azure OpenAI API version exposed through the APIM gateway.')
param apimOpenAiApiVersion string = '2024-10-21'

@description('Existing Log Analytics workspace resource ID to reuse.')
param existingLogAnalyticsResourceId string = ''

@description('Existing Application Insights component resource ID to reuse.')
param existingApplicationInsightsResourceId string = ''

@description('Existing Application Insights connection string. Required when reusing an existing App Insights (ARM cannot read it).')
@secure()
param existingApplicationInsightsConnectionString string = ''

@description('Existing Container Registry resource ID to reuse. Must live in the same resource group.')
param existingContainerRegistryResourceId string = ''

// ============================================================
// Derived values
// ============================================================
var tags = {
  env: environmentName
  'azd-env-name': environmentName
  workload: 'foundry-agent-observability'
}
var resourceToken = uniqueString(subscription().id, resourceGroupName, location)
var aiFoundryAccountNameEff = !empty(aiFoundryResourceName) ? aiFoundryResourceName : 'aif-${resourceToken}'
var aiFoundryProjectNameEff = !empty(aiFoundryProjectName) ? aiFoundryProjectName : 'project-${resourceToken}'

// ============================================================
// Resource Group
// ============================================================
resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

// ============================================================
// AI Foundry (account + project + capabilityHost + peripherals)
// ============================================================
module aiFoundry 'modules/ai-foundry.bicep' = {
  scope: rg
  name: 'ai-foundry'
  params: {
    location: aiDeploymentsLocation
    tags: tags
    aiFoundryAccountName: aiFoundryAccountNameEff
    aiFoundryProjectName: aiFoundryProjectNameEff
    resourceToken: resourceToken
    principalId: principalId
    principalType: principalType
    deployments: aiProjectDeployments
    enableMonitoring: enableMonitoring
    enableHostedAgents: enableHostedAgents
    existingLogAnalyticsResourceId: existingLogAnalyticsResourceId
    existingApplicationInsightsResourceId: existingApplicationInsightsResourceId
    existingApplicationInsightsConnectionString: existingApplicationInsightsConnectionString
    existingContainerRegistryResourceId: existingContainerRegistryResourceId
    aiSearchResourceId: enableAiSearch ? aiSearch!.outputs.resourceId : ''
    aiSearchEndpoint: enableAiSearch ? aiSearch!.outputs.endpoint : ''
    aiSearchName: enableAiSearch ? aiSearch!.outputs.name : ''
  }
}

// ============================================================
// Azure AI Search (Foundry IQ / Agent Knowledge backend)
// ============================================================
module aiSearch 'modules/ai-search.bicep' = if (enableAiSearch) {
  scope: rg
  name: 'ai-search'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    sku: aiSearchSku
  }
}

// ============================================================
// Compute layer (optional)
// ============================================================
module compute 'modules/compute-layer.bicep' = if (enableComputeLayer) {
  scope: rg
  name: 'compute-layer'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    logAnalyticsResourceId: aiFoundry.outputs.logAnalyticsResourceId
    applicationInsightsConnectionString: aiFoundry.outputs.applicationInsightsConnectionString
    applicationInsightsResourceId: aiFoundry.outputs.applicationInsightsResourceId
    aiFoundryAccountId: aiFoundry.outputs.accountId
    aiFoundryAccountName: aiFoundry.outputs.accountName
    aiFoundryProjectName: aiFoundry.outputs.projectName
    aiFoundryProjectEndpoint: aiFoundry.outputs.projectEndpoint
    containerRegistryResourceId: aiFoundry.outputs.containerRegistryResourceId
    containerRegistryLoginServer: aiFoundry.outputs.containerRegistryLoginServer
    mafContainerImage: mafContainerImage
    langGraphContainerImage: langGraphContainerImage
    modelDeploymentName: modelDeploymentName
    apimPublisherEmail: apimPublisherEmail
    apimAgentsJwtAudience: apimAgentsJwtAudience
    apimAgentsJwtTenantId: empty(apimAgentsJwtTenantId) ? tenant().tenantId : apimAgentsJwtTenantId
    apimSecretsToKeyVault: apimSecretsToKeyVault
    apimTokenLimitTpm: apimTokenLimitTpm
    apimOpenAiApiVersion: apimOpenAiApiVersion
  }
}

// ============================================================
// Outputs — azd will promote these to environment variables
// ============================================================
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location

// Foundry
output AZURE_AI_ACCOUNT_ID string = aiFoundry.outputs.accountId
output AZURE_AI_ACCOUNT_NAME string = aiFoundry.outputs.accountName
output AZURE_AI_PROJECT_ID string = aiFoundry.outputs.projectId
output AZURE_AI_PROJECT_NAME string = aiFoundry.outputs.projectName
output AZURE_AI_FOUNDRY_PROJECT_ID string = aiFoundry.outputs.projectId
output AZURE_AI_PROJECT_ENDPOINT string = aiFoundry.outputs.projectEndpoint
output AZURE_OPENAI_ENDPOINT string = aiFoundry.outputs.openAiEndpoint
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = modelDeploymentName

// Monitoring
output APPLICATIONINSIGHTS_RESOURCE_ID string = aiFoundry.outputs.applicationInsightsResourceId
output APPLICATIONINSIGHTS_CONNECTION_STRING string = aiFoundry.outputs.applicationInsightsConnectionString

// Container Registry
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = aiFoundry.outputs.containerRegistryLoginServer
output AZURE_CONTAINER_REGISTRY_RESOURCE_ID string = aiFoundry.outputs.containerRegistryResourceId
output AZURE_CONTAINER_REGISTRY_NAME string = aiFoundry.outputs.containerRegistryName

// Azure AI Search (Foundry IQ)
output AZURE_AI_SEARCH_ENDPOINT string = enableAiSearch ? aiSearch!.outputs.endpoint : ''
output AZURE_AI_SEARCH_NAME string = enableAiSearch ? aiSearch!.outputs.name : ''
output AZURE_AI_SEARCH_RESOURCE_ID string = enableAiSearch ? aiSearch!.outputs.resourceId : ''

// Compute layer
output ACA_ENVIRONMENT_NAME string = enableComputeLayer ? compute!.outputs.acaEnvironmentName : ''
output MAF_AGENT_FQDN string = enableComputeLayer ? compute!.outputs.mafAgentFqdn : ''
output LANGGRAPH_AGENT_FQDN string = enableComputeLayer ? compute!.outputs.langGraphAgentFqdn : ''
output APIM_GATEWAY_URL string = enableComputeLayer ? compute!.outputs.apimGatewayUrl : ''
output APIM_MAF_AGENT_URL string = enableComputeLayer ? compute!.outputs.apimMafAgentUrl : ''
output APIM_LANGGRAPH_AGENT_URL string = enableComputeLayer ? compute!.outputs.apimLangGraphAgentUrl : ''
output APIM_OPENAI_GATEWAY_URL string = enableComputeLayer ? compute!.outputs.apimOpenAiGatewayUrl : ''
output APIM_AGENTS_SUBSCRIPTION_RESOURCE_ID string = enableComputeLayer ? compute!.outputs.apimAgentsSubscriptionResourceId : ''
output APIM_OPENAI_SUBSCRIPTION_RESOURCE_ID string = enableComputeLayer ? compute!.outputs.apimOpenAiSubscriptionResourceId : ''
output APIM_OPENAI_KEY_SECRET_NAME string = enableComputeLayer ? compute!.outputs.apimOpenAiKeySecretName : ''
output APIM_AGENTS_KEY_SECRET_NAME string = enableComputeLayer ? compute!.outputs.apimAgentsKeySecretName : ''
output COSMOS_ENDPOINT string = enableComputeLayer ? compute!.outputs.cosmosEndpoint : ''
output KEYVAULT_URI string = enableComputeLayer ? compute!.outputs.keyVaultUri : ''
output APPS_IDENTITY_CLIENT_ID string = enableComputeLayer ? compute!.outputs.appsIdentityClientId : ''
