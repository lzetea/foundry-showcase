// ============================================================
// Azure AI Search — backs the Foundry IQ / Agent Knowledge surface.
// Provisioned via AVM avm/res/search/search-service.
// ============================================================

targetScope = 'resourceGroup'

@description('Location of the search service.')
param location string

@description('Tags applied to the search service.')
param tags object = {}

@description('Deterministic naming token.')
param resourceToken string

@description('SKU for the search service.')
@allowed([
  'free'
  'basic'
  'standard'
  'standard2'
  'standard3'
  'storage_optimized_l1'
  'storage_optimized_l2'
])
param sku string = 'standard'

@description('Number of replicas.')
@minValue(1)
@maxValue(12)
param replicaCount int = 1

@description('Number of partitions.')
@allowed([ 1, 2, 3, 4, 6, 12 ])
param partitionCount int = 1

@description('Allow data-plane API keys in addition to AAD. Set to "disabled" for AAD-only.')
@allowed([ 'enabled', 'disabled' ])
param disableLocalAuth string = 'enabled'

// ============================================================
// Search service (AVM)
// ============================================================
module searchService 'br/public:avm/res/search/search-service:0.11.1' = {
  name: 'srch-${resourceToken}'
  params: {
    name: 'srch-${resourceToken}'
    location: location
    tags: tags
    sku: sku
    replicaCount: replicaCount
    partitionCount: partitionCount
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: disableLocalAuth == 'disabled'
    authOptions: disableLocalAuth == 'disabled' ? null : {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
    managedIdentities: {
      systemAssigned: true
    }
    semanticSearch: 'standard'
  }
}

output resourceId string = searchService.outputs.resourceId
output name string = searchService.outputs.name
output endpoint string = 'https://${searchService.outputs.name}.search.windows.net'
output systemAssignedMIPrincipalId string = searchService.outputs.?systemAssignedMIPrincipalId ?? ''
