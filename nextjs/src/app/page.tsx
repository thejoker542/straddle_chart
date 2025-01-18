"use client"

import { useState, useEffect, useRef } from 'react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { ZoomIn, ZoomOut, Home, LineChart, Settings2 } from 'lucide-react'
import * as echarts from 'echarts'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogDescription } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Socket } from 'socket.io-client'
import io from 'socket.io-client'

// Add market update interface
interface MarketUpdate {
  symbol: string
  timestamp: number
  ltp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  bid: number
  ask: number
  bid_qty: number
  ask_qty: number
  change: number
  change_percent: number
}

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'
const socket = io(BACKEND_URL)

const INDEX_SYMBOLS = {
  "NIFTY": "NSE:NIFTY50-INDEX",
  "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
  "FINNIFTY": "NSE:FINNIFTY-INDEX",
  "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
  "SENSEX": "BSE:SENSEX-INDEX",
  "BANKEX": "BSE:BANKEX-INDEX"
}

const generateTimeLabels = () => {
  const labels = []
  const data1 = []
  const data2 = []
  const data3 = []
  
  for (let hour = 9; hour <= 15; hour++) {
    for (let minute = 0; minute < 60; minute += 15) {
      const time = `${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}`
      labels.push(time)
      data1.push([time, 470 + Math.random() * 50])
      data2.push([time, 12550 + Math.random() * 100])
      data3.push([time, 12580 + Math.random() * 100])
    }
  }
  return { labels, data1, data2, data3 }
}

const formatDate = (dateStr: string) => {
  const date = new Date(dateStr)
  
  // Format the date as 'YYYY-MM-DD HH:MM'
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  
  return `${year}-${month}-${day} ${hours}:${minutes}`
}

const resampleData = (
  data: [string, number, number, number, number, number][],
  timeframeMinutes: number
): [string, number, number, number, number, number][] => {
  if (!data.length) return []
  if (timeframeMinutes === 1) return data // Return original data for 1-minute timeframe
  
  const resampledData: [string, number, number, number, number, number][] = []
  let currentBatch: [string, number, number, number, number, number][] = []
  let currentTimestamp = new Date(data[0][0])
  currentTimestamp.setSeconds(0, 0)
  
  // Round down to nearest timeframe interval
  const minutes = currentTimestamp.getMinutes()
  const roundedMinutes = Math.floor(minutes / timeframeMinutes) * timeframeMinutes
  currentTimestamp.setMinutes(roundedMinutes)

  data.forEach((candle) => {
    const candleTime = new Date(candle[0])
    const candleTimestamp = candleTime.getTime()
    const intervalEnd = new Date(currentTimestamp.getTime() + timeframeMinutes * 60000)

    if (candleTimestamp < intervalEnd.getTime()) {
      currentBatch.push(candle)
    } else {
      if (currentBatch.length > 0) {
        // Calculate OHLCV for the batch
        const open = currentBatch[0][1]
        const high = Math.max(...currentBatch.map(c => c[2]))
        const low = Math.min(...currentBatch.map(c => c[3]))
        const close = currentBatch[currentBatch.length - 1][4]
        const volume = currentBatch.reduce((sum, c) => sum + c[5], 0)
        
        resampledData.push([
          formatDate(currentTimestamp.toISOString()),
          open,
          high,
          low,
          close,
          volume
        ])
      }
      // Move to next interval
      currentTimestamp = new Date(intervalEnd)
      currentBatch = [candle]
    }
  })

  // Handle the last batch
  if (currentBatch.length > 0) {
    const open = currentBatch[0][1]
    const high = Math.max(...currentBatch.map(c => c[2]))
    const low = Math.min(...currentBatch.map(c => c[3]))
    const close = currentBatch[currentBatch.length - 1][4]
    const volume = currentBatch.reduce((sum, c) => sum + c[5], 0)
    
    resampledData.push([
      formatDate(currentTimestamp.toISOString()),
      open,
      high,
      low,
      close,
      volume
    ])
  }

  // Log the resampled data length
  console.log(`Resampled Data Points for Timeframe ${timeframeMinutes} minutes: ${resampledData.length} (from ${data.length} points)`)

  return resampledData
}

// Add indicator state types
interface IndicatorSettings {
  bollinger: {
    enabled: boolean
    period: number
    stdDev: number
  }
  ma: {
    enabled: boolean
    period: number
    type: 'simple' | 'exponential'
  }
  rsi: {
    enabled: boolean
    period: number
  }
  vwap: {
    enabled: boolean
  }
  series: {
    ce: boolean
    pe: boolean
  }
}

export default function ModernChart() {
  // Initialize states
  const [selectedIndex, setSelectedIndex] = useState("NIFTY")
  const [selectedStrike, setSelectedStrike] = useState<string | null>(null)
  const [selectedTimeframe, setSelectedTimeframe] = useState("1")
  const [strikeOptions, setStrikeOptions] = useState<string[]>([])
  const [currentPrice, setCurrentPrice] = useState<number>(0)
  const [isLoading, setIsLoading] = useState(false)
  const [rawCEData, setRawCEData] = useState<[string, number, number, number, number, number][]>([])
  const [rawPEData, setRawPEData] = useState<[string, number, number, number, number, number][]>([])
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  // Add state for indicators
  const [indicatorSettings, setIndicatorSettings] = useState<IndicatorSettings>({
    bollinger: {
      enabled: true,
      period: 20,
      stdDev: 2
    },
    ma: {
      enabled: true,
      period: 20,
      type: 'simple'
    },
    rsi: {
      enabled: true,
      period: 14
    },
    vwap: {
      enabled: true
    },
    series: {
      ce: false,
      pe: false
    }
  })
  // Add state for live data
  const [liveData, setLiveData] = useState<{[key: string]: MarketUpdate}>({})
  const subscribedSymbols = useRef<Set<string>>(new Set())

  // Function to subscribe to symbols
  const subscribeToSymbols = async (symbols: string[]) => {
    try {
      // Filter out already subscribed symbols
      const newSymbols = symbols.filter(s => !subscribedSymbols.current.has(s))
      if (newSymbols.length === 0) return

      console.log('Subscribing to symbols:', newSymbols)
      
      const response = await fetch(`${BACKEND_URL}/subscribe`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ symbols: newSymbols }),
      })

      if (!response.ok) {
        throw new Error('Failed to subscribe to symbols')
      }

      // Add to subscribed set
      newSymbols.forEach(s => subscribedSymbols.current.add(s))
    } catch (error) {
      console.error('Error subscribing to symbols:', error)
    }
  }

  // Update socket handler with proper typing
  useEffect(() => {
    socket.on('market_update', (data: MarketUpdate) => {
      console.log('Received market update:', data)
      setLiveData(prev => ({
        ...prev,
        [data.symbol]: data
      }))
    })

    return () => {
      socket.off('market_update')
    }
  }, [])

  // Update chart with live data
  useEffect(() => {
    if (chartInstance.current && Object.keys(liveData).length > 0) {
      const option = chartInstance.current.getOption()
      const series = option.series as any[]
      let updated = false

      series.forEach((s: any) => {
        if (liveData[s.name]) {
          const lastIndex = s.data.length - 1
          if (lastIndex >= 0) {
            s.data[lastIndex] = liveData[s.name].ltp
            updated = true
          }
        }
      })

      if (updated) {
        chartInstance.current.setOption({ series })
      }
    }
  }, [liveData])

  const fetchStrikePrices = async (index: string) => {
    try {
      setIsLoading(true)
      const response = await fetch(`${BACKEND_URL}/index-strikes/${index}`)
      if (!response.ok) throw new Error('Failed to fetch strike prices')
      
      const data = await response.json()
      setStrikeOptions(data.strikes)
      setCurrentPrice(data.current_price)
      // Set the default strike
      if (data.default_strike) {
        setSelectedStrike(data.default_strike.toString())
      }
    } catch (error) {
      console.error('Error fetching strike prices:', error)
    } finally {
      setIsLoading(false)
    }
  }

  // Modify handleChartUpdate to subscribe to symbols
  const handleChartUpdate = async () => {
    try {
      if (!selectedStrike) {
        console.log('No strike selected, skipping chart update')
        return
      }

      setIsLoading(true)
      const response = await fetch(`${BACKEND_URL}/historical_straddle/${selectedIndex}/${selectedStrike}`)
      if (!response.ok) throw new Error('Failed to fetch chart data')
      
      const data = await response.json()
      
      // Subscribe to CE and PE symbols
      const symbolsToSubscribe = [data.ce_data.symbol, data.pe_data.symbol]
      await subscribeToSymbols(symbolsToSubscribe)
      
      processChartData(data)
    } catch (error) {
      console.error('Error updating chart:', error)
    } finally {
      setIsLoading(false)
    }
  }

  // Load initial data and setup chart
  useEffect(() => {
    const initializeData = async () => {
      await fetchStrikePrices(selectedIndex)
    }
    initializeData()
  }, [selectedIndex])

  // Update chart when strike is set
  useEffect(() => {
    if (selectedStrike) {
      handleChartUpdate()
    }
  }, [selectedStrike])

  const processChartData = (data: any) => {
    // Get symbols directly from response
    const ceSymbol = data.ce_data.symbol
    const peSymbol = data.pe_data.symbol
    
    // Store raw data
    setRawCEData(data.ce_data.data)
    setRawPEData(data.pe_data.data)
    
    console.log(`Raw Data Points - ${ceSymbol}:`, data.ce_data.data.length)
    console.log(`Raw Data Points - ${peSymbol}:`, data.pe_data.data.length)
    
    // Filter and resample data
    const timeframeMinutes = parseInt(selectedTimeframe)
    let resampledCEData = resampleData(data.ce_data.data, timeframeMinutes)
    let resampledPEData = resampleData(data.pe_data.data, timeframeMinutes)

    // Sort data in ascending order
    resampledCEData.sort((a, b) => new Date(a[0]).getTime() - new Date(b[0]).getTime())
    resampledPEData.sort((a, b) => new Date(a[0]).getTime() - new Date(b[0]).getTime())
    
    // Create straddle data
    const straddleData = createStraddleData(resampledCEData, resampledPEData)
    
    if (chartInstance.current) {
      const timestamps = straddleData.map(d => String(d[0]))
      updateChartWithData(
        chartInstance.current, 
        timestamps, 
        straddleData, 
        resampledCEData, 
        resampledPEData,
        ceSymbol,
        peSymbol
      )
    }
  }

  const createStraddleData = (
    resampledCEData: [string, number, number, number, number, number][],
    resampledPEData: [string, number, number, number, number, number][]
  ): [string, number, number, number, number, number][] => {
    // Create a Map for PE data for quick lookup by timestamp
    const peDataMap = new Map<string, [string, number, number, number, number, number]>()
    resampledPEData.forEach(pePoint => {
      peDataMap.set(pePoint[0], pePoint)
    })
    
    // Calculate straddle data by aligning CE and PE data based on timestamp
    const straddleData: [string, number, number, number, number, number][] = []
    
    resampledCEData.forEach(cePoint => {
      const [timestamp, ceOpen, ceHigh, ceLow, ceClose, ceVolume] = cePoint
      const pePoint = peDataMap.get(timestamp)
      
      if (pePoint) {
        const [, peOpen, peHigh, peLow, peClose, peVolume] = pePoint
        
        straddleData.push([
          timestamp,                        // Timestamp
          ceOpen + peOpen,                  // Straddle Open = CE Open + PE Open
          ceHigh + peHigh,                  // Straddle High = CE High + PE High
          ceLow + peLow,                    // Straddle Low = CE Low + PE Low
          ceClose + peClose,                // Straddle Close = CE Close + PE Close
          ceVolume + peVolume               // Straddle Volume = CE Volume + PE Volume
        ])
      }
    })

    return straddleData.sort((a, b) => new Date(a[0]).getTime() - new Date(b[0]).getTime())
  }

  // Add indicator calculation functions
  const calculateBollingerBands = (data: number[], period: number, stdDev: number) => {
    const sma = data.map((_, i) => {
      if (i < period - 1) return null
      const slice = data.slice(i - period + 1, i + 1)
      return slice.reduce((sum, val) => sum + val, 0) / period
    })

    const stdDevs = data.map((_, i) => {
      if (i < period - 1) return null
      const slice = data.slice(i - period + 1, i + 1)
      const mean = sma[i]!
      const squaredDiffs = slice.map(val => Math.pow(val - mean, 2))
      const variance = squaredDiffs.reduce((sum, val) => sum + val, 0) / period
      return Math.sqrt(variance)
    })

    return {
      middle: sma,
      upper: sma.map((val, i) => val === null ? null : val + (stdDevs[i]! * stdDev)),
      lower: sma.map((val, i) => val === null ? null : val - (stdDevs[i]! * stdDev))
    }
  }

  const calculateMA = (data: number[], period: number, type: 'simple' | 'exponential') => {
    if (type === 'simple') {
      return data.map((_, i) => {
        if (i < period - 1) return null
        const slice = data.slice(i - period + 1, i + 1)
        return slice.reduce((sum, val) => sum + val, 0) / period
      })
    } else {
      const multiplier = 2 / (period + 1)
      const ema = [data[0]]
      for (let i = 1; i < data.length; i++) {
        ema[i] = (data[i] - ema[i - 1]) * multiplier + ema[i - 1]
      }
      return ema
    }
  }

  const calculateRSI = (data: number[], period: number) => {
    const changes = data.map((val, i) => i === 0 ? 0 : val - data[i - 1])
    const gains = changes.map(val => val > 0 ? val : 0)
    const losses = changes.map(val => val < 0 ? -val : 0)

    const avgGain = gains.map((_, i) => {
      if (i < period) return null
      const slice = gains.slice(i - period + 1, i + 1)
      return slice.reduce((sum, val) => sum + val, 0) / period
    })

    const avgLoss = losses.map((_, i) => {
      if (i < period) return null
      const slice = losses.slice(i - period + 1, i + 1)
      return slice.reduce((sum, val) => sum + val, 0) / period
    })

    return avgGain.map((gain, i) => {
      if (gain === null) return null
      const rs = gain / avgLoss[i]!
      return 100 - (100 / (1 + rs))
    })
  }

  const calculateVWAP = (data: [string, number, number, number, number, number][]) => {
    let cumulativeTPV = 0
    let cumulativeVolume = 0
    
    return data.map(candle => {
      const [, open, high, low, close, volume] = candle
      const typicalPrice = (high + low + close) / 3
      cumulativeTPV += typicalPrice * volume
      cumulativeVolume += volume
      return cumulativeTPV / cumulativeVolume
    })
  }

  // Modify updateChartWithData to include indicators
  const updateChartWithData = (
    chartInstance: echarts.ECharts,
    timestamps: string[],
    straddleData: [string, number, number, number, number, number][],
    resampledCEData: [string, number, number, number, number, number][],
    resampledPEData: [string, number, number, number, number, number][],
    ceSymbol: string,
    peSymbol: string
  ) => {
    console.log('Updating chart with settings:', indicatorSettings)
    
    // Calculate initial zoom range to show last 600 points
    const totalPoints = timestamps.length
    const zoomStart = Math.max(0, ((totalPoints - 600) / totalPoints) * 100)
    const zoomEnd = 100

    // Create simplified arrays with just timestamp and close price
    const simplifiedStraddleData = straddleData.map(d => ({
      timestamp: d[0],
      close: d[4]
    }))
    const simplifiedCEData = resampledCEData.map(d => ({
      timestamp: d[0],
      close: d[4]
    }))
    const simplifiedPEData = resampledPEData.map(d => ({
      timestamp: d[0],
      close: d[4]
    }))

    // Prepare data arrays for chart
    const straddlePrices = simplifiedStraddleData.map(d => d.close)
    const cePrices = simplifiedCEData.map(d => d.close)
    const pePrices = simplifiedPEData.map(d => d.close)

    // Calculate indicators if enabled
    const indicators: any = {}
    if (indicatorSettings.bollinger.enabled) {
      console.log('Calculating Bollinger Bands...')
      indicators.bollinger = calculateBollingerBands(
        straddlePrices,
        indicatorSettings.bollinger.period,
        indicatorSettings.bollinger.stdDev
      )
    }

    if (indicatorSettings.ma.enabled) {
      console.log('Calculating Moving Average...')
      indicators.ma = calculateMA(
        straddlePrices,
        indicatorSettings.ma.period,
        indicatorSettings.ma.type
      )
    }

    if (indicatorSettings.rsi.enabled) {
      console.log('Calculating RSI...')
      indicators.rsi = calculateRSI(straddlePrices, indicatorSettings.rsi.period)
    }

    if (indicatorSettings.vwap.enabled) {
      console.log('Calculating VWAP...')
      indicators.vwap = calculateVWAP(straddleData)
    }

    // Create series array
    const series: any[] = [
      {
        name: 'Straddle',
        type: 'line',
        smooth: false,
        symbol: 'none',
        data: straddlePrices,
        lineStyle: {
          width: 2,
          color: 'rgb(59, 130, 246)'
        }
      }
    ]

    // Add CE/PE series if enabled
    if (indicatorSettings.series.ce) {
      console.log('Adding CE series with data points:', cePrices.length)
      series.push({
        name: ceSymbol,
        type: 'line',
        smooth: false,
        symbol: 'none',
        data: cePrices,
        lineStyle: { width: 2, color: 'rgb(16, 185, 129)' }
      })
    }

    if (indicatorSettings.series.pe) {
      console.log('Adding PE series with data points:', pePrices.length)
      series.push({
        name: peSymbol,
        type: 'line',
        smooth: false,
        symbol: 'none',
        data: pePrices,
        lineStyle: { width: 2, color: 'rgb(249, 115, 22)' }
      })
    }

    // Add indicator series
    if (indicatorSettings.bollinger.enabled) {
      console.log('Adding Bollinger Bands series')
      series.push(
        {
          name: 'BB Upper',
          type: 'line',
          smooth: false,
          symbol: 'none',
          data: indicators.bollinger.upper,
          lineStyle: { width: 1, type: 'dashed', color: 'rgba(250, 84, 28, 0.8)' }
        },
        {
          name: 'BB Middle',
          type: 'line',
          smooth: false,
          symbol: 'none',
          data: indicators.bollinger.middle,
          lineStyle: { width: 1, type: 'dashed', color: 'rgba(250, 84, 28, 0.8)' }
        },
        {
          name: 'BB Lower',
          type: 'line',
          smooth: false,
          symbol: 'none',
          data: indicators.bollinger.lower,
          lineStyle: { width: 1, type: 'dashed', color: 'rgba(250, 84, 28, 0.8)' }
        }
      )
    }

    if (indicatorSettings.ma.enabled) {
      console.log('Adding Moving Average series')
      series.push({
        name: `${indicatorSettings.ma.type === 'simple' ? 'SMA' : 'EMA'} (${indicatorSettings.ma.period})`,
        type: 'line',
        smooth: false,
        symbol: 'none',
        data: indicators.ma,
        lineStyle: { width: 1.5, color: 'rgba(234, 179, 8, 0.9)' }
      })
    }

    if (indicatorSettings.vwap.enabled) {
      console.log('Adding VWAP series')
      series.push({
        name: 'VWAP',
        type: 'line',
        smooth: false,
        symbol: 'none',
        data: indicators.vwap,
        lineStyle: { width: 1.5, color: 'rgba(168, 85, 247, 0.9)' }
      })
    }

    const chartSeries = indicatorSettings.rsi.enabled ? [
      ...series,
      {
        name: 'RSI',
        type: 'line',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: indicators.rsi,
        smooth: false,
        symbol: 'none',
        lineStyle: { width: 1.5, color: 'rgba(147, 51, 234, 0.9)' }
      }
    ] : series

    // Create chart options
    const options: echarts.EChartsOption = {
      animation: false,
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(255, 255, 255, 0.9)',
        borderColor: 'rgba(0, 0, 0, 0.1)',
        borderWidth: 1,
        padding: 12,
        textStyle: {
          color: '#1a1a1a'
        },
        formatter: (params: any) => {
          const date = params[0].axisValue
          let result = `<div class="font-medium">${date}</div>`
          params.forEach((param: any) => {
            result += `<div class="flex items-center gap-2">
              <span style="color:${param.color}">${param.seriesName}</span>: 
              <span class="font-medium">${param.value?.toFixed(2) || 'N/A'}</span>
            </div>`
          })
          return result
        }
      },
      legend: {
        data: chartSeries.map(s => s.name),
        bottom: indicatorSettings.rsi.enabled ? '25%' : 0,
        padding: 20,
        icon: 'circle'
      },
      grid: indicatorSettings.rsi.enabled ? [
        { left: '3%', right: '4%', bottom: '30%', top: '3%', containLabel: true },
        { left: '3%', right: '4%', bottom: '5%', height: '20%', containLabel: true }
      ] : [
        { left: '3%', right: '4%', bottom: '12%', top: '3%', containLabel: true }
      ],
      xAxis: indicatorSettings.rsi.enabled ? [
        {
          type: 'category',
          data: timestamps,
          boundaryGap: false,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            formatter: (value: string) => value,
            rotate: 45,
            showMaxLabel: true,
            interval: Math.floor(timestamps.length / 20)
          }
        },
        {
          type: 'category',
          gridIndex: 1,
          data: timestamps,
          boundaryGap: false,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { show: false }
        }
      ] : {
        type: 'category',
        data: timestamps,
        boundaryGap: false,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          formatter: (value: string) => value,
          rotate: 45,
          showMaxLabel: true,
          interval: Math.floor(timestamps.length / 20)
        }
      },
      yAxis: indicatorSettings.rsi.enabled ? [
        {
          type: 'value',
          position: 'right',
          splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.05)' } },
          axisLabel: { formatter: (value: number) => value.toFixed(1) }
        },
        {
          type: 'value',
          gridIndex: 1,
          position: 'right',
          splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.05)' } },
          min: 0,
          max: 100,
          axisLabel: { formatter: '{value}' }
        }
      ] : {
        type: 'value',
        position: 'right',
        splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.05)' } },
        axisLabel: { formatter: (value: number) => value.toFixed(1) }
      },
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: indicatorSettings.rsi.enabled ? [0, 1] : [0],
          start: zoomStart,
          end: zoomEnd,
          minValueSpan: 60 * 1
        },
        {
          type: 'slider',
          show: true,
          xAxisIndex: indicatorSettings.rsi.enabled ? [0, 1] : [0],
          start: zoomStart,
          end: zoomEnd,
          bottom: indicatorSettings.rsi.enabled ? '25%' : 10,
          height: 20,
          minValueSpan: 60 * 1
        }
      ],
      series: chartSeries
    }

    console.log('Setting chart options with series:', chartSeries.map(s => s.name))
    chartInstance.setOption(options, true) // Use true to force update
    chartInstance.resize()
  }

  // Initialize chart
  useEffect(() => {
    if (!chartRef.current) return

    chartInstance.current = echarts.init(chartRef.current)

    const handleResize = () => {
      chartInstance.current?.resize()
    }

    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chartInstance.current?.dispose()
    }
  }, [])

  // Zoom handlers
  const handleZoomIn = () => {
    if (!chartInstance.current) return
    const option = chartInstance.current.getOption()
    const dataZoom = option.dataZoom as { start: number; end: number }[] | undefined
    if (!dataZoom?.[0]) return
    
    const range = dataZoom[0].end - dataZoom[0].start
    const center = (dataZoom[0].start + dataZoom[0].end) / 2
    const newRange = range * 0.8
    
    chartInstance.current.setOption({
      dataZoom: [{
        start: Math.max(0, center - newRange / 2),
        end: Math.min(100, center + newRange / 2)
      }]
    })
  }

  const handleZoomOut = () => {
    if (!chartInstance.current) return
    const option = chartInstance.current.getOption()
    const dataZoom = option.dataZoom as { start: number; end: number }[] | undefined
    if (!dataZoom?.[0]) return
    
    const range = dataZoom[0].end - dataZoom[0].start
    const center = (dataZoom[0].start + dataZoom[0].end) / 2
    const newRange = range * 1.2
    
    chartInstance.current.setOption({
      dataZoom: [{
        start: Math.max(0, center - newRange / 2),
        end: Math.min(100, center + newRange / 2)
      }]
    })
  }

  const handleReset = () => {
    if (!chartInstance.current) return
    const option = chartInstance.current.getOption()
    const totalPoints = (option.xAxis as any)[0].data.length
    const zoomStart = Math.max(0, ((totalPoints - 600) / totalPoints) * 100)
    
    chartInstance.current.setOption({
      dataZoom: [{
        start: zoomStart,
        end: 100
      }]
    })
  }

  // Add useEffect to update chart when indicator settings change
  useEffect(() => {
    if (chartInstance.current && rawCEData.length > 0 && rawPEData.length > 0) {
      const timeframeMinutes = parseInt(selectedTimeframe)
      const resampledCEData = resampleData(rawCEData, timeframeMinutes)
      const resampledPEData = resampleData(rawPEData, timeframeMinutes)
      const straddleData = createStraddleData(resampledCEData, resampledPEData)
      const timestamps = straddleData.map(d => String(d[0]))
      
      // Get symbols from the raw data
      const ceSymbol = rawCEData[0]?.[0].split(' ')[0] || 'CE'
      const peSymbol = rawPEData[0]?.[0].split(' ')[0] || 'PE'
      
      updateChartWithData(
        chartInstance.current,
        timestamps,
        straddleData,
        resampledCEData,
        resampledPEData,
        ceSymbol,
        peSymbol
      )
    }
  }, [indicatorSettings, selectedTimeframe, rawCEData, rawPEData])

  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100 p-8">
      <Card className="w-full max-w-6xl mx-auto backdrop-blur-xl bg-white/80 border border-gray-200/50 shadow-xl">
        <CardHeader className="border-b border-gray-100">
          <div className="flex justify-between items-center flex-wrap gap-4">
            <div className="flex items-center gap-4 flex-wrap">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-500">Index</span>
                <Select value={selectedIndex} onValueChange={setSelectedIndex}>
                  <SelectTrigger className="w-[180px] bg-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.keys(INDEX_SYMBOLS).map((index) => (
                      <SelectItem key={index} value={index}>
                        {index}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-500">Strike</span>
                <Select 
                  value={selectedStrike || ''} 
                  onValueChange={setSelectedStrike}
                >
                  <SelectTrigger className="w-[120px] bg-white" disabled={isLoading || strikeOptions.length === 0}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {strikeOptions.map((strike) => (
                      <SelectItem key={strike} value={strike.toString()}>
                        {strike}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-gray-500">Timeframe</span>
                <Select defaultValue={selectedTimeframe} onValueChange={setSelectedTimeframe}>
                  <SelectTrigger className="w-[120px] bg-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">1 min</SelectItem>
                    <SelectItem value="3">3 min</SelectItem>
                    <SelectItem value="5">5 min</SelectItem>
                    <SelectItem value="15">15 min</SelectItem>
                    <SelectItem value="30">30 min</SelectItem>
                    <SelectItem value="60">1 hour</SelectItem>
                    <SelectItem value="1440">1 day</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button 
                variant="default" 
                size="default" 
                onClick={handleChartUpdate}
                className="flex items-center gap-2"
                disabled={isLoading || !selectedStrike}
              >
                <LineChart className="h-4 w-4" />
                {isLoading ? 'Loading...' : 'Chart'}
              </Button>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="icon" onClick={handleZoomIn}>
                <ZoomIn className="h-4 w-4" />
              </Button>
              <Button variant="outline" size="icon" onClick={handleZoomOut}>
                <ZoomOut className="h-4 w-4" />
              </Button>
              <Button variant="outline" size="icon" onClick={handleReset}>
                <Home className="h-4 w-4" />
              </Button>
            </div>
            <div className="flex items-center gap-2">
              <Dialog>
                <DialogTrigger asChild>
                  <Button variant="outline" size="sm" className="gap-2">
                    <Settings2 className="w-4 h-4" />
                    Indicators
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Indicator Settings</DialogTitle>
                    <DialogDescription>
                      Configure technical indicators and series visibility for the chart.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-6 py-4">
                    <div className="space-y-4">
                      <h4 className="font-medium">Series</h4>
                      <div className="flex items-center justify-between">
                        <Label htmlFor="ce-toggle">CE</Label>
                        <Switch
                          id="ce-toggle"
                          checked={indicatorSettings.series.ce}
                          onCheckedChange={(checked) => setIndicatorSettings(prev => ({
                            ...prev,
                            series: { ...prev.series, ce: checked }
                          }))}
                        />
                      </div>
                      <div className="flex items-center justify-between">
                        <Label htmlFor="pe-toggle">PE</Label>
                        <Switch
                          id="pe-toggle"
                          checked={indicatorSettings.series.pe}
                          onCheckedChange={(checked) => setIndicatorSettings(prev => ({
                            ...prev,
                            series: { ...prev.series, pe: checked }
                          }))}
                        />
                      </div>
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <Label htmlFor="bb-toggle">Bollinger Bands</Label>
                        <Switch
                          id="bb-toggle"
                          checked={indicatorSettings.bollinger.enabled}
                          onCheckedChange={(checked) => setIndicatorSettings(prev => ({
                            ...prev,
                            bollinger: { ...prev.bollinger, enabled: checked }
                          }))}
                        />
                      </div>
                      {indicatorSettings.bollinger.enabled && (
                        <div className="space-y-4 pl-4">
                          <div className="space-y-2">
                            <Label htmlFor="bb-period">Period</Label>
                            <Input
                              id="bb-period"
                              type="number"
                              value={indicatorSettings.bollinger.period}
                              onChange={(e) => setIndicatorSettings(prev => ({
                                ...prev,
                                bollinger: { ...prev.bollinger, period: parseInt(e.target.value) }
                              }))}
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="bb-stddev">Standard Deviation</Label>
                            <Input
                              id="bb-stddev"
                              type="number"
                              step="0.1"
                              value={indicatorSettings.bollinger.stdDev}
                              onChange={(e) => setIndicatorSettings(prev => ({
                                ...prev,
                                bollinger: { ...prev.bollinger, stdDev: parseFloat(e.target.value) }
                              }))}
                            />
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <Label htmlFor="ma-toggle">Moving Average</Label>
                        <Switch
                          id="ma-toggle"
                          checked={indicatorSettings.ma.enabled}
                          onCheckedChange={(checked) => setIndicatorSettings(prev => ({
                            ...prev,
                            ma: { ...prev.ma, enabled: checked }
                          }))}
                        />
                      </div>
                      {indicatorSettings.ma.enabled && (
                        <div className="space-y-4 pl-4">
                          <div className="space-y-2">
                            <Label htmlFor="ma-period">Period</Label>
                            <Input
                              id="ma-period"
                              type="number"
                              value={indicatorSettings.ma.period}
                              onChange={(e) => setIndicatorSettings(prev => ({
                                ...prev,
                                ma: { ...prev.ma, period: parseInt(e.target.value) }
                              }))}
                            />
                          </div>
                          <div className="space-y-2">
                            <Label htmlFor="ma-type">Type</Label>
                            <Select
                              value={indicatorSettings.ma.type}
                              onValueChange={(value: 'simple' | 'exponential') => setIndicatorSettings(prev => ({
                                ...prev,
                                ma: { ...prev.ma, type: value }
                              }))}
                            >
                              <SelectTrigger id="ma-type">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="simple">Simple</SelectItem>
                                <SelectItem value="exponential">Exponential</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <Label htmlFor="rsi-toggle">RSI</Label>
                        <Switch
                          id="rsi-toggle"
                          checked={indicatorSettings.rsi.enabled}
                          onCheckedChange={(checked) => setIndicatorSettings(prev => ({
                            ...prev,
                            rsi: { ...prev.rsi, enabled: checked }
                          }))}
                        />
                      </div>
                      {indicatorSettings.rsi.enabled && (
                        <div className="space-y-4 pl-4">
                          <div className="space-y-2">
                            <Label htmlFor="rsi-period">Period</Label>
                            <Input
                              id="rsi-period"
                              type="number"
                              value={indicatorSettings.rsi.period}
                              onChange={(e) => setIndicatorSettings(prev => ({
                                ...prev,
                                rsi: { ...prev.rsi, period: parseInt(e.target.value) }
                              }))}
                            />
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <Label htmlFor="vwap-toggle">VWAP</Label>
                        <Switch
                          id="vwap-toggle"
                          checked={indicatorSettings.vwap.enabled}
                          onCheckedChange={(checked) => setIndicatorSettings(prev => ({
                            ...prev,
                            vwap: { ...prev.vwap, enabled: checked }
                          }))}
                        />
                      </div>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-6">
          <div className="h-[500px]" ref={chartRef} />
          <div className="mt-6 grid grid-cols-3 md:grid-cols-6 gap-4 p-4 bg-gray-50/50 rounded-lg">
            <div className="space-y-1">
              <div className="text-sm text-gray-500">Straddle Price</div>
              <div className="text-lg font-semibold">473</div>
            </div>
            <div className="space-y-1">
              <div className="text-sm text-gray-500">{selectedIndex} Spot</div>
              <div className="text-lg font-semibold">{currentPrice.toFixed(1)}</div>
            </div>
            <div className="space-y-1">
              <div className="text-sm text-gray-500">Synthetic Future</div>
              <div className="text-lg font-semibold">12598.00</div>
            </div>
            <div className="space-y-1">
              <div className="text-sm text-gray-500">Straddle Strike</div>
              <div className="text-lg font-semibold">{selectedStrike}</div>
            </div>
            <div className="space-y-1">
              <div className="text-sm text-gray-500">Days to Expiry</div>
              <div className="text-lg font-semibold">22</div>
            </div>
            <div className="space-y-1">
              <div className="text-sm text-gray-500">Last Updated</div>
              <div className="text-lg font-semibold">03:30 PM</div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
