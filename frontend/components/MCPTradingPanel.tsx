'use client';

import { useState, useEffect, useCallback } from 'react';
import { api } from '../lib/api';

interface MCPTool {
    name: string;
    description: string;
}

interface Position {
    symbol: string;
    netQty: number;
    avgPrice: number;
    ltp: number;
    pl: number;
    productType: string;
}

interface Order {
    id: string;
    symbol: string;
    side: number;
    qty: number;
    limitPrice: number;
    status: number;
}

interface MCPTradingPanelProps {
    onBack: () => void;
}

export default function MCPTradingPanel({ onBack }: MCPTradingPanelProps) {
    const [activeTab, setActiveTab] = useState<'portfolio' | 'orders' | 'trade'>('portfolio');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Portfolio data
    const [positions, setPositions] = useState<Position[]>([]);
    const [holdings, setHoldings] = useState<any[]>([]);
    const [funds, setFunds] = useState<any>(null);
    const [orders, setOrders] = useState<Order[]>([]);
    const [mcpStatus, setMcpStatus] = useState<any>(null);

    // Order form
    const [orderForm, setOrderForm] = useState({
        symbol: 'NSE:SBIN-EQ',
        qty: 1,
        side: 'BUY',
        orderType: 'MARKET',
        productType: 'INTRADAY',
        limitPrice: 0,
    });
    const [orderResult, setOrderResult] = useState<string | null>(null);

    // Fetch MCP status
    const fetchMCPStatus = useCallback(async () => {
        try {
            const status = await api.fetch('/mcp/status');
            setMcpStatus(status);
        } catch (err: any) {
            console.error('Failed to fetch MCP status:', err);
        }
    }, []);

    // Call MCP tool
    const callMCPTool = async (toolName: string, args: any = {}) => {
        const response = await api.fetch('/mcp/call', {
            method: 'POST',
            body: JSON.stringify({ name: toolName, arguments: args }),
        });
        return response;
    };

    // Fetch portfolio data
    const fetchPortfolio = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const [positionsRes, holdingsRes, fundsRes] = await Promise.all([
                callMCPTool('get_positions'),
                callMCPTool('get_holdings'),
                callMCPTool('get_funds'),
            ]);

            // Parse the text responses (MCP returns markdown text)
            // For now we'll display the raw text
            setPositions(positionsRes);
            setHoldings(holdingsRes);
            setFunds(fundsRes);
        } catch (err: any) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, []);

    // Fetch orders
    const fetchOrders = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const result = await callMCPTool('get_orders');
            setOrders(result);
        } catch (err: any) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, []);

    // Place order
    const placeOrder = async () => {
        setLoading(true);
        setOrderResult(null);
        setError(null);
        try {
            const result = await callMCPTool('place_order', {
                symbol: orderForm.symbol,
                qty: orderForm.qty,
                side: orderForm.side,
                order_type: orderForm.orderType,
                product_type: orderForm.productType,
                limit_price: orderForm.limitPrice,
            });

            if (result.isError) {
                setError(result.content[0]?.text || 'Order failed');
            } else {
                setOrderResult(result.content[0]?.text || 'Order placed successfully');
                // Refresh orders
                fetchOrders();
            }
        } catch (err: any) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    // Cancel order
    const cancelOrder = async (orderId: string) => {
        try {
            await callMCPTool('cancel_order', { order_id: orderId });
            fetchOrders();
        } catch (err: any) {
            setError(err.message);
        }
    };

    useEffect(() => {
        fetchMCPStatus();
        if (activeTab === 'portfolio') {
            fetchPortfolio();
        } else if (activeTab === 'orders') {
            fetchOrders();
        }
    }, [activeTab, fetchMCPStatus, fetchPortfolio, fetchOrders]);

    // Extract text from MCP response
    const extractText = (response: any): string => {
        if (!response) return 'No data';
        if (response.isError) return response.content?.[0]?.text || 'Error';
        return response.content?.[0]?.text || JSON.stringify(response);
    };

    return (
        <div className="min-h-screen bg-zinc-50 dark:bg-black text-zinc-900 dark:text-zinc-100 p-4 md:p-8">
            {/* Header */}
            <header className="max-w-7xl mx-auto flex justify-between items-center mb-8">
                <div>
                    <button
                        onClick={onBack}
                        className="text-zinc-500 hover:text-zinc-900 dark:hover:text-white text-sm font-bold uppercase tracking-wider mb-2 flex items-center gap-2"
                    >
                        ← Back to Dashboard
                    </button>
                    <h1 className="text-3xl font-black italic tracking-tighter text-zinc-900 dark:text-white uppercase">
                        Trading<span className="text-emerald-500">.</span>MCP
                    </h1>
                    <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest mt-1">
                        AI-Powered Trading Interface
                    </p>
                </div>

                {/* MCP Status */}
                <div className="flex items-center gap-3">
                    <div className={`px-3 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider ${mcpStatus?.authenticated
                            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                            : 'bg-red-500/20 text-red-400 border border-red-500/30'
                        }`}>
                        {mcpStatus?.authenticated ? '🟢 Connected' : '🔴 Not Authenticated'}
                    </div>
                    <span className="text-xs text-zinc-500">{mcpStatus?.tools_count} tools</span>
                </div>
            </header>

            {/* Tabs */}
            <div className="max-w-7xl mx-auto mb-6">
                <div className="flex gap-2 bg-zinc-100 dark:bg-zinc-900 p-1 rounded-xl w-fit">
                    {[
                        { id: 'portfolio', label: '📊 Portfolio', icon: '📊' },
                        { id: 'orders', label: '📋 Orders', icon: '📋' },
                        { id: 'trade', label: '⚡ Place Order', icon: '⚡' },
                    ].map((tab) => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id as any)}
                            className={`px-4 py-2 rounded-lg text-sm font-bold uppercase tracking-wider transition-all ${activeTab === tab.id
                                    ? 'bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white shadow-lg'
                                    : 'text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300'
                                }`}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Error Display */}
            {error && (
                <div className="max-w-7xl mx-auto mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm">
                    ❌ {error}
                </div>
            )}

            {/* Main Content */}
            <main className="max-w-7xl mx-auto">
                {/* Portfolio Tab */}
                {activeTab === 'portfolio' && (
                    <div className="space-y-6">
                        {/* Funds Card */}
                        <div className="bg-white dark:bg-zinc-900 rounded-2xl p-6 border border-zinc-200 dark:border-zinc-800">
                            <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                                💰 Available Funds
                                <button onClick={fetchPortfolio} className="text-xs text-blue-500 hover:text-blue-400">
                                    ↻ Refresh
                                </button>
                            </h2>
                            {loading ? (
                                <div className="animate-pulse h-20 bg-zinc-100 dark:bg-zinc-800 rounded-lg"></div>
                            ) : (
                                <pre className="text-sm text-zinc-600 dark:text-zinc-400 whitespace-pre-wrap font-mono bg-zinc-50 dark:bg-zinc-800/50 p-4 rounded-lg">
                                    {extractText(funds)}
                                </pre>
                            )}
                        </div>

                        {/* Positions Card */}
                        <div className="bg-white dark:bg-zinc-900 rounded-2xl p-6 border border-zinc-200 dark:border-zinc-800">
                            <h2 className="text-lg font-bold mb-4">📈 Open Positions</h2>
                            {loading ? (
                                <div className="animate-pulse h-32 bg-zinc-100 dark:bg-zinc-800 rounded-lg"></div>
                            ) : (
                                <pre className="text-sm text-zinc-600 dark:text-zinc-400 whitespace-pre-wrap font-mono bg-zinc-50 dark:bg-zinc-800/50 p-4 rounded-lg">
                                    {extractText(positions)}
                                </pre>
                            )}
                        </div>

                        {/* Holdings Card */}
                        <div className="bg-white dark:bg-zinc-900 rounded-2xl p-6 border border-zinc-200 dark:border-zinc-800">
                            <h2 className="text-lg font-bold mb-4">📊 Holdings</h2>
                            {loading ? (
                                <div className="animate-pulse h-32 bg-zinc-100 dark:bg-zinc-800 rounded-lg"></div>
                            ) : (
                                <pre className="text-sm text-zinc-600 dark:text-zinc-400 whitespace-pre-wrap font-mono bg-zinc-50 dark:bg-zinc-800/50 p-4 rounded-lg">
                                    {extractText(holdings)}
                                </pre>
                            )}
                        </div>
                    </div>
                )}

                {/* Orders Tab */}
                {activeTab === 'orders' && (
                    <div className="bg-white dark:bg-zinc-900 rounded-2xl p-6 border border-zinc-200 dark:border-zinc-800">
                        <h2 className="text-lg font-bold mb-4 flex items-center gap-2">
                            📋 Today's Orders
                            <button onClick={fetchOrders} className="text-xs text-blue-500 hover:text-blue-400">
                                ↻ Refresh
                            </button>
                        </h2>
                        {loading ? (
                            <div className="animate-pulse h-32 bg-zinc-100 dark:bg-zinc-800 rounded-lg"></div>
                        ) : (
                            <pre className="text-sm text-zinc-600 dark:text-zinc-400 whitespace-pre-wrap font-mono bg-zinc-50 dark:bg-zinc-800/50 p-4 rounded-lg">
                                {extractText(orders)}
                            </pre>
                        )}
                    </div>
                )}

                {/* Trade Tab */}
                {activeTab === 'trade' && (
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                        {/* Order Form */}
                        <div className="bg-white dark:bg-zinc-900 rounded-2xl p-6 border border-zinc-200 dark:border-zinc-800">
                            <h2 className="text-lg font-bold mb-6">⚡ Place Order</h2>

                            <div className="space-y-4">
                                {/* Symbol */}
                                <div>
                                    <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 mb-2">
                                        Symbol
                                    </label>
                                    <input
                                        type="text"
                                        value={orderForm.symbol}
                                        onChange={(e) => setOrderForm({ ...orderForm, symbol: e.target.value })}
                                        placeholder="NSE:SBIN-EQ"
                                        className="w-full px-4 py-3 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    />
                                </div>

                                {/* Quantity */}
                                <div>
                                    <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 mb-2">
                                        Quantity
                                    </label>
                                    <input
                                        type="number"
                                        value={orderForm.qty}
                                        onChange={(e) => setOrderForm({ ...orderForm, qty: parseInt(e.target.value) || 1 })}
                                        min="1"
                                        className="w-full px-4 py-3 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    />
                                </div>

                                {/* Side */}
                                <div>
                                    <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 mb-2">
                                        Side
                                    </label>
                                    <div className="flex gap-2">
                                        <button
                                            onClick={() => setOrderForm({ ...orderForm, side: 'BUY' })}
                                            className={`flex-1 py-3 rounded-xl font-bold uppercase text-sm transition-all ${orderForm.side === 'BUY'
                                                    ? 'bg-emerald-500 text-white shadow-lg shadow-emerald-500/30'
                                                    : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500 hover:text-zinc-700'
                                                }`}
                                        >
                                            🟢 Buy
                                        </button>
                                        <button
                                            onClick={() => setOrderForm({ ...orderForm, side: 'SELL' })}
                                            className={`flex-1 py-3 rounded-xl font-bold uppercase text-sm transition-all ${orderForm.side === 'SELL'
                                                    ? 'bg-red-500 text-white shadow-lg shadow-red-500/30'
                                                    : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500 hover:text-zinc-700'
                                                }`}
                                        >
                                            🔴 Sell
                                        </button>
                                    </div>
                                </div>

                                {/* Order Type */}
                                <div>
                                    <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 mb-2">
                                        Order Type
                                    </label>
                                    <select
                                        value={orderForm.orderType}
                                        onChange={(e) => setOrderForm({ ...orderForm, orderType: e.target.value })}
                                        className="w-full px-4 py-3 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    >
                                        <option value="MARKET">Market</option>
                                        <option value="LIMIT">Limit</option>
                                        <option value="STOP_LIMIT">Stop Limit</option>
                                        <option value="STOP_MARKET">Stop Market</option>
                                    </select>
                                </div>

                                {/* Product Type */}
                                <div>
                                    <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 mb-2">
                                        Product Type
                                    </label>
                                    <select
                                        value={orderForm.productType}
                                        onChange={(e) => setOrderForm({ ...orderForm, productType: e.target.value })}
                                        className="w-full px-4 py-3 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                                    >
                                        <option value="INTRADAY">Intraday (MIS)</option>
                                        <option value="CNC">Delivery (CNC)</option>
                                        <option value="MARGIN">Margin (F&O)</option>
                                    </select>
                                </div>

                                {/* Limit Price (conditional) */}
                                {(orderForm.orderType === 'LIMIT' || orderForm.orderType === 'STOP_LIMIT') && (
                                    <div>
                                        <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 mb-2">
                                            Limit Price
                                        </label>
                                        <input
                                            type="number"
                                            value={orderForm.limitPrice}
                                            onChange={(e) => setOrderForm({ ...orderForm, limitPrice: parseFloat(e.target.value) || 0 })}
                                            step="0.05"
                                            className="w-full px-4 py-3 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                                        />
                                    </div>
                                )}

                                {/* Place Order Button */}
                                <button
                                    onClick={placeOrder}
                                    disabled={loading || !mcpStatus?.authenticated}
                                    className={`w-full py-4 rounded-xl font-bold uppercase text-sm tracking-wider transition-all ${orderForm.side === 'BUY'
                                            ? 'bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700'
                                            : 'bg-gradient-to-r from-red-600 to-rose-600 hover:from-red-700 hover:to-rose-700'
                                        } text-white shadow-lg disabled:opacity-50 disabled:cursor-not-allowed`}
                                >
                                    {loading ? '⏳ Placing Order...' : `${orderForm.side === 'BUY' ? '🟢' : '🔴'} Place ${orderForm.side} Order`}
                                </button>

                                {!mcpStatus?.authenticated && (
                                    <p className="text-xs text-amber-500 text-center">
                                        ⚠️ Please authenticate with Fyers first to place orders
                                    </p>
                                )}
                            </div>
                        </div>

                        {/* Order Result & Quick Actions */}
                        <div className="space-y-6">
                            {/* Order Result */}
                            {orderResult && (
                                <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-2xl p-6">
                                    <h3 className="text-sm font-bold text-emerald-400 uppercase tracking-wider mb-2">
                                        ✅ Order Result
                                    </h3>
                                    <pre className="text-sm text-emerald-300 whitespace-pre-wrap font-mono">
                                        {orderResult}
                                    </pre>
                                </div>
                            )}

                            {/* Quick Symbols */}
                            <div className="bg-white dark:bg-zinc-900 rounded-2xl p-6 border border-zinc-200 dark:border-zinc-800">
                                <h3 className="text-sm font-bold uppercase tracking-wider text-zinc-500 mb-4">
                                    Quick Symbols
                                </h3>
                                <div className="flex flex-wrap gap-2">
                                    {[
                                        'NSE:SBIN-EQ',
                                        'NSE:RELIANCE-EQ',
                                        'NSE:TCS-EQ',
                                        'NSE:HDFCBANK-EQ',
                                        'NSE:INFY-EQ',
                                        'NSE:ICICIBANK-EQ',
                                        'NSE:TATAMOTORS-EQ',
                                        'NSE:BAJFINANCE-EQ',
                                    ].map((symbol) => (
                                        <button
                                            key={symbol}
                                            onClick={() => setOrderForm({ ...orderForm, symbol })}
                                            className={`px-3 py-1.5 rounded-lg text-xs font-mono transition-all ${orderForm.symbol === symbol
                                                    ? 'bg-blue-500 text-white'
                                                    : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700'
                                                }`}
                                        >
                                            {symbol.split(':')[1].replace('-EQ', '')}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* MCP Info */}
                            <div className="bg-white dark:bg-zinc-900 rounded-2xl p-6 border border-zinc-200 dark:border-zinc-800">
                                <h3 className="text-sm font-bold uppercase tracking-wider text-zinc-500 mb-4">
                                    🤖 MCP Server Info
                                </h3>
                                <div className="space-y-2 text-sm text-zinc-600 dark:text-zinc-400">
                                    <p>• Server: <span className="font-mono text-blue-400">{mcpStatus?.server || 'N/A'}</span></p>
                                    <p>• Version: <span className="font-mono">{mcpStatus?.version || 'N/A'}</span></p>
                                    <p>• Tools: <span className="font-mono text-emerald-400">{mcpStatus?.tools_count || 0}</span></p>
                                    <p>• User: <span className="font-mono">{mcpStatus?.user || 'Not logged in'}</span></p>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </main>
        </div>
    );
}
