// Neo4j Graph API Service
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface GraphNode {
  id: string;
  label: string;
  properties?: Record<string, any>;
}

export interface GraphEdge {
  from: string;
  to: string;
  type: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface NeighborData {
  node_id: string;
  neighbors: string[];
}

export interface PathData {
  from: string;
  to: string;
  path: string[];
  length: number;
}

export interface CentralityData {
  id: string;
  degree: number;
}

export interface CommunityData {
  id: string;
  community: string[];
}

// Graph API Service Class
export class GraphApiService {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    });

    if (!response.ok) {
      throw new Error(`API request failed: ${response.status} ${response.statusText}`);
    }

    return response.json();
  }

  // Get full graph data with pagination
  async getFullGraph(limit: number = 1000, nodeTypes?: string): Promise<GraphData & {total_nodes: number, total_edges: number, has_more: boolean}> {
    const params = new URLSearchParams();
    if (limit) params.append('limit', limit.toString());
    if (nodeTypes) params.append('node_types', nodeTypes);
    
    const queryString = params.toString();
    const endpoint = queryString ? `/graph/full_graph?${queryString}` : '/graph/full_graph';
    
    return this.request<GraphData & {total_nodes: number, total_edges: number, has_more: boolean}>(endpoint);
  }

  // Get all nodes
  async getAllNodes(): Promise<GraphNode[]> {
    return this.request<GraphNode[]>('/graph/nodes');
  }

  // Get all relationships
  async getAllRelationships(): Promise<GraphEdge[]> {
    return this.request<GraphEdge[]>('/graph/relationships');
  }

  // Run custom Cypher query
  async runQuery(query: string): Promise<any[]> {
    return this.request<any[]>('/graph/query', {
      method: 'POST',
      body: JSON.stringify({ query }),
    });
  }

  // Get neighbors of a node
  async getNeighbors(nodeId: string): Promise<NeighborData> {
    return this.request<NeighborData>('/graph/neighbors', {
      method: 'POST',
      body: JSON.stringify({ node_id: nodeId }),
    });
  }

  // Get shortest path between nodes
  async getShortestPath(fromId: string, toId: string): Promise<PathData> {
    return this.request<PathData>('/graph/shortest_path', {
      method: 'POST',
      body: JSON.stringify({ from_id: fromId, to_id: toId }),
    });
  }

  // Get degree centrality
  async getCentrality(label: string): Promise<CentralityData[]> {
    return this.request<CentralityData[]>('/graph/centrality', {
      method: 'POST',
      body: JSON.stringify({ label }),
    });
  }

  // Get community detection
  async getCommunities(label: string): Promise<CommunityData[]> {
    return this.request<CommunityData[]>('/graph/community_detection', {
      method: 'POST',
      body: JSON.stringify({ label }),
    });
  }

  // Add entity
  async addEntity(label: string, name: string): Promise<{ message: string; id: string }> {
    return this.request<{ message: string; id: string }>('/graph/add_entity', {
      method: 'POST',
      body: JSON.stringify({ label, name }),
    });
  }

  // Batch ingest data
  async batchIngest(data: {
    people?: any[];
    messages?: any[];
    calls?: any[];
    relationships?: any[];
  }): Promise<{ message: string }> {
    return this.request<{ message: string }>('/graph/batch_ingest', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Get graph statistics
  async getStats(): Promise<Record<string, number>> {
    return this.request<Record<string, number>>('/graph/stats');
  }

  // Get sample data
  async getSampleData(nodeType: string = 'User', limit: number = 10): Promise<{nodes: GraphNode[], count: number}> {
    return this.request<{nodes: GraphNode[], count: number}>(`/graph/sample?node_type=${nodeType}&limit=${limit}`);
  }
}

// Create singleton instance
export const graphApi = new GraphApiService();

// Utility functions
export const graphUtils = {
  // Transform data for vis-network
  transformForVisNetwork: (graphData: GraphData) => {
    const nodes = graphData.nodes.map(node => ({
      id: node.id,
      label: node.properties?.name || node.id,
      group: node.label,
      title: `${node.label}: ${node.properties?.name || node.id}`,
      ...node.properties,
    }));

    const edges = graphData.edges.map(edge => ({
      from: edge.from,
      to: edge.to,
      label: edge.type,
      arrows: 'to',
    }));

    return { nodes, edges };
  },

  // Get node statistics
  getNodeStats: (graphData: GraphData) => {
    const nodeCounts = graphData.nodes.reduce((acc, node) => {
      acc[node.label] = (acc[node.label] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);

    return {
      totalNodes: graphData.nodes.length,
      totalEdges: graphData.edges.length,
      nodeTypes: nodeCounts,
    };
  },

  // Filter nodes by type
  filterNodesByType: (graphData: GraphData, nodeType: string) => {
    const filteredNodes = graphData.nodes.filter(node => node.label === nodeType);
    const filteredEdges = graphData.edges.filter(edge => 
      filteredNodes.some(node => node.id === edge.from || node.id === edge.to)
    );
    
    return {
      nodes: filteredNodes,
      edges: filteredEdges,
    };
  },
};
