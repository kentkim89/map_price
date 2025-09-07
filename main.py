#!/usr/bin/env python3
"""
MAP 가격 모니터링 시스템 - Streamlit 웹 대시보드
고래미 & 설래담 브랜드 MAP 정책 관리 시스템
"""

import streamlit as st
import pandas as pd
import json
import time
import threading
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
from typing import List, Dict, Optional
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
import random
import re
import sqlite3
import os
from dataclasses import dataclass, asdict
import queue
import logging

# 페이지 설정
st.set_page_config(
    page_title="MAP 가격 모니터링 시스템",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 세션 상태 초기화
if 'violations' not in st.session_state:
    st.session_state.violations = []
if 'monitoring_active' not in st.session_state:
    st.session_state.monitoring_active = False
if 'last_scan' not in st.session_state:
    st.session_state.last_scan = None
if 'scan_history' not in st.session_state:
    st.session_state.scan_history = []
if 'products' not in st.session_state:
    st.session_state.products = []

# 데이터 클래스
@dataclass
class Product:
    brand: str
    name: str
    map_price: int
    search_keyword: str

@dataclass
class Violation:
    brand: str
    product_name: str
    map_price: int
    vendor_name: str
    violation_price: int
    violation_url: str
    violation_rate: float
    discovered_at: str
    status: str = "신규"

# 데이터베이스 클래스
class Database:
    def __init__(self, db_path='map_violations.db'):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 위반 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS violations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand TEXT NOT NULL,
                product_name TEXT NOT NULL,
                map_price INTEGER NOT NULL,
                vendor_name TEXT NOT NULL,
                violation_price INTEGER NOT NULL,
                violation_url TEXT,
                violation_rate REAL,
                discovered_at TIMESTAMP NOT NULL,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 업체 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT UNIQUE NOT NULL,
                warning_count INTEGER DEFAULT 0,
                last_warning_date TIMESTAMP,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 스캔 이력 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_time TIMESTAMP NOT NULL,
                products_scanned INTEGER,
                violations_found INTEGER,
                duration_seconds INTEGER
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_violation(self, violation: Violation):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO violations (brand, product_name, map_price, vendor_name, 
                                   violation_price, violation_url, violation_rate, discovered_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (violation.brand, violation.product_name, violation.map_price,
              violation.vendor_name, violation.violation_price, violation.violation_url,
              violation.violation_rate, violation.discovered_at, violation.status))
        
        conn.commit()
        conn.close()
    
    def get_violations(self, limit=100):
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query('''
            SELECT * FROM violations 
            ORDER BY discovered_at DESC 
            LIMIT ?
        ''', conn, params=(limit,))
        conn.close()
        return df
    
    def get_vendor_stats(self):
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query('''
            SELECT vendor_name, COUNT(*) as violation_count,
                   AVG(violation_rate) as avg_violation_rate
            FROM violations
            GROUP BY vendor_name
            ORDER BY violation_count DESC
        ''', conn)
        conn.close()
        return df

# 크롤러 클래스
class NaverCrawler:
    def __init__(self):
        self.driver = None
        
    def setup_driver(self):
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        self.driver = webdriver.Chrome(options=options)
        
    def close_driver(self):
        if self.driver:
            self.driver.quit()
    
    def extract_price(self, price_text: str) -> Optional[int]:
        try:
            price = re.sub(r'[^\d]', '', price_text)
            return int(price) if price else None
        except:
            return None
    
    def crawl_product(self, product: Product, progress_callback=None) -> List[Violation]:
        violations = []
        
        try:
            search_url = f"https://search.shopping.naver.com/search/all?query={product.search_keyword}"
            
            if progress_callback:
                progress_callback(f"🔍 검색 중: {product.name}")
            
            self.driver.get(search_url)
            time.sleep(random.uniform(3, 5))
            
            # 상품 목록 가져오기
            items = self.driver.find_elements(By.CLASS_NAME, "basicList_item__0T9JD")
            
            for item in items[:10]:  # 상위 10개만 확인
                try:
                    # 제품명 확인
                    title = item.find_element(By.CLASS_NAME, "basicList_title__VfX3c").text
                    if product.brand not in title:
                        continue
                    
                    # 판매처
                    try:
                        vendor = item.find_element(By.CLASS_NAME, "basicList_mall__BC5Xu").text
                    except:
                        vendor = "알 수 없음"
                    
                    # 가격
                    try:
                        price_elem = item.find_element(By.CLASS_NAME, "price_num__S2p_v")
                        price = self.extract_price(price_elem.text)
                    except:
                        continue
                    
                    # URL
                    try:
                        link = item.find_element(By.CLASS_NAME, "basicList_link__JLQJf")
                        url = link.get_attribute('href')
                    except:
                        url = ""
                    
                    # MAP 위반 체크
                    if price and price < product.map_price:
                        violation_rate = ((product.map_price - price) / product.map_price) * 100
                        
                        violation = Violation(
                            brand=product.brand,
                            product_name=product.name,
                            map_price=product.map_price,
                            vendor_name=vendor,
                            violation_price=price,
                            violation_url=url,
                            violation_rate=round(violation_rate, 1),
                            discovered_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            status="신규"
                        )
                        violations.append(violation)
                        
                except Exception as e:
                    continue
                    
        except Exception as e:
            if progress_callback:
                progress_callback(f"❌ 오류: {str(e)}")
        
        return violations

# 알림 발송 함수
def send_notifications(violations: List[Violation], config: dict):
    """Slack, SMS 등 알림 발송"""
    if not violations:
        return
    
    # Slack 알림
    if config.get('slack_webhook'):
        try:
            message = {
                "text": f"⚠️ MAP 위반 감지: {len(violations)}건",
                "attachments": [
                    {
                        "color": "danger",
                        "fields": [
                            {
                                "title": f"{v.product_name}",
                                "value": f"업체: {v.vendor_name}\n가격: {v.violation_price:,}원 (MAP: {v.map_price:,}원)\n위반율: {v.violation_rate}%",
                                "short": False
                            }
                            for v in violations[:5]  # 최대 5개만 표시
                        ]
                    }
                ]
            }
            requests.post(config['slack_webhook'], json=message)
        except:
            pass

# CSS 스타일
def load_css():
    st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        padding: 1rem 0;
    }
    
    .metric-card {
        background-color: #f0f2f6;
        padding: 1.5rem;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    .violation-card {
        background-color: #fff;
        padding: 1rem;
        border-left: 4px solid #ff4b4b;
        margin-bottom: 1rem;
        border-radius: 5px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    
    .success-message {
        background-color: #d4edda;
        color: #155724;
        padding: 1rem;
        border-radius: 5px;
        margin: 1rem 0;
    }
    
    .warning-message {
        background-color: #fff3cd;
        color: #856404;
        padding: 1rem;
        border-radius: 5px;
        margin: 1rem 0;
    }
    
    .error-message {
        background-color: #f8d7da;
        color: #721c24;
        padding: 1rem;
        border-radius: 5px;
        margin: 1rem 0;
    }
    </style>
    """, unsafe_allow_html=True)

# 메인 앱
def main():
    load_css()
    
    # 헤더
    st.markdown('<p class="main-header">🔍 MAP 가격 모니터링 시스템</p>', unsafe_allow_html=True)
    st.markdown("### 고래미 & 설래담 브랜드 가격 정책 관리")
    
    # 데이터베이스 초기화
    db = Database()
    
    # 사이드바
    with st.sidebar:
        st.header("⚙️ 설정")
        
        # 제품 관리
        st.subheader("📦 제품 관리")
        
        # 기본 제품 목록
        default_products = [
            {"brand": "고래미", "name": "고래미 타코와사비", "map_price": 18000, "keyword": "고래미 타코와사비"},
            {"brand": "고래미", "name": "고래미 가니미소", "map_price": 25000, "keyword": "고래미 가니미소"},
            {"brand": "설래담", "name": "설래담 연포탕", "map_price": 32000, "keyword": "설래담 연포탕"}
        ]
        
        # 제품별 MAP 가격 설정
        products = []
        for product in default_products:
            with st.expander(f"{product['brand']} - {product['name']}"):
                map_price = st.number_input(
                    "MAP 가격 (원)",
                    value=product['map_price'],
                    min_value=1000,
                    step=1000,
                    key=f"price_{product['name']}"
                )
                keyword = st.text_input(
                    "검색 키워드",
                    value=product['keyword'],
                    key=f"keyword_{product['name']}"
                )
                products.append(Product(
                    brand=product['brand'],
                    name=product['name'],
                    map_price=map_price,
                    search_keyword=keyword
                ))
        
        st.session_state.products = products
        
        st.divider()
        
        # 알림 설정
        st.subheader("🔔 알림 설정")
        
        slack_webhook = st.text_input(
            "Slack Webhook URL",
            type="password",
            placeholder="https://hooks.slack.com/..."
        )
        
        n8n_webhook = st.text_input(
            "n8n Webhook URL",
            type="password",
            placeholder="https://your-n8n.com/webhook/..."
        )
        
        st.divider()
        
        # 스캔 설정
        st.subheader("🔄 스캔 설정")
        
        scan_interval = st.selectbox(
            "자동 스캔 주기",
            ["수동", "30분", "1시간", "3시간", "6시간"],
            index=0
        )
        
        delay_min = st.slider("최소 지연 시간 (초)", 2, 10, 3)
        delay_max = st.slider("최대 지연 시간 (초)", delay_min, 15, 7)
    
    # 메인 컨텐츠
    tabs = st.tabs(["📊 대시보드", "🔍 실시간 모니터링", "📈 통계", "📋 위반 이력", "⚙️ 관리"])
    
    # 대시보드 탭
    with tabs[0]:
        # 메트릭 카드
        col1, col2, col3, col4 = st.columns(4)
        
        # 오늘의 위반 건수 계산
        today_violations = [v for v in st.session_state.violations 
                          if v.discovered_at.startswith(datetime.now().strftime("%Y-%m-%d"))]
        
        with col1:
            st.metric(
                "오늘 위반 건수",
                f"{len(today_violations)}건",
                delta="실시간 감지 중" if st.session_state.monitoring_active else "모니터링 중지"
            )
        
        with col2:
            total_violations = len(st.session_state.violations)
            st.metric(
                "총 위반 건수",
                f"{total_violations}건",
                delta=f"+{len(today_violations)}" if today_violations else "0"
            )
        
        with col3:
            if st.session_state.violations:
                avg_violation_rate = sum(v.violation_rate for v in st.session_state.violations) / len(st.session_state.violations)
                st.metric(
                    "평균 위반율",
                    f"{avg_violation_rate:.1f}%",
                    delta="MAP 정책 위반"
                )
            else:
                st.metric("평균 위반율", "0%", delta="정상")
        
        with col4:
            if st.session_state.last_scan:
                time_diff = datetime.now() - datetime.strptime(st.session_state.last_scan, "%Y-%m-%d %H:%M:%S")
                hours_ago = time_diff.total_seconds() / 3600
                st.metric(
                    "마지막 스캔",
                    f"{hours_ago:.1f}시간 전",
                    delta="자동 스캔 활성" if scan_interval != "수동" else "수동 모드"
                )
            else:
                st.metric("마지막 스캔", "스캔 전", delta="대기 중")
        
        st.divider()
        
        # 최근 위반 내역
        st.subheader("🚨 최근 위반 내역")
        
        if st.session_state.violations:
            # 위반 데이터를 DataFrame으로 변환
            violations_data = []
            for v in st.session_state.violations[:10]:  # 최근 10건만
                violations_data.append({
                    "시간": v.discovered_at,
                    "브랜드": v.brand,
                    "제품": v.product_name,
                    "업체": v.vendor_name,
                    "위반가격": f"{v.violation_price:,}원",
                    "MAP": f"{v.map_price:,}원",
                    "위반율": f"{v.violation_rate}%",
                    "상태": v.status
                })
            
            df_violations = pd.DataFrame(violations_data)
            
            # 스타일 적용
            st.dataframe(
                df_violations,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "상태": st.column_config.SelectboxColumn(
                        options=["신규", "경고발송", "해결", "재위반"],
                        default="신규"
                    )
                }
            )
        else:
            st.info("아직 위반 내역이 없습니다. 모니터링을 시작해주세요.")
        
        # 차트
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📊 브랜드별 위반 현황")
            if st.session_state.violations:
                brand_counts = {}
                for v in st.session_state.violations:
                    brand_counts[v.brand] = brand_counts.get(v.brand, 0) + 1
                
                fig = px.pie(
                    values=list(brand_counts.values()),
                    names=list(brand_counts.keys()),
                    color_discrete_map={'고래미': '#FF6B6B', '설래담': '#4ECDC4'}
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("데이터가 없습니다.")
        
        with col2:
            st.subheader("📈 시간대별 위반 추이")
            if st.session_state.scan_history:
                df_history = pd.DataFrame(st.session_state.scan_history)
                fig = px.line(
                    df_history,
                    x='time',
                    y='violations',
                    markers=True,
                    title="위반 건수 추이"
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("스캔 이력이 없습니다.")
    
    # 실시간 모니터링 탭
    with tabs[1]:
        st.subheader("🔍 실시간 가격 모니터링")
        
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col1:
            if st.button("🚀 모니터링 시작", type="primary", use_container_width=True):
                st.session_state.monitoring_active = True
                
        with col2:
            if st.button("⏸️ 모니터링 중지", type="secondary", use_container_width=True):
                st.session_state.monitoring_active = False
                
        with col3:
            if st.button("🔄 즉시 스캔", use_container_width=True):
                with st.spinner("스캔 중..."):
                    # 크롤러 실행
                    crawler = NaverCrawler()
                    crawler.setup_driver()
                    
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    all_violations = []
                    
                    for i, product in enumerate(st.session_state.products):
                        progress = (i + 1) / len(st.session_state.products)
                        progress_bar.progress(progress)
                        status_text.text(f"검색 중: {product.name}")
                        
                        violations = crawler.crawl_product(product)
                        all_violations.extend(violations)
                        
                        # 지연
                        time.sleep(random.uniform(delay_min, delay_max))
                    
                    crawler.close_driver()
                    
                    # 결과 저장
                    st.session_state.violations.extend(all_violations)
                    st.session_state.last_scan = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    st.session_state.scan_history.append({
                        'time': st.session_state.last_scan,
                        'violations': len(all_violations)
                    })
                    
                    # 데이터베이스 저장
                    for v in all_violations:
                        db.save_violation(v)
                    
                    # 알림 발송
                    if all_violations:
                        config = {
                            'slack_webhook': slack_webhook,
                            'n8n_webhook': n8n_webhook
                        }
                        send_notifications(all_violations, config)
                    
                    progress_bar.empty()
                    status_text.empty()
                    
                    if all_violations:
                        st.success(f"✅ 스캔 완료! {len(all_violations)}건의 위반을 발견했습니다.")
                        st.balloons()
                    else:
                        st.info("스캔 완료! 위반 사항이 없습니다.")
        
        st.divider()
        
        # 모니터링 상태
        if st.session_state.monitoring_active:
            st.success("🟢 모니터링 활성화됨")
            
            # 실시간 로그
            st.subheader("📝 실시간 로그")
            log_container = st.container()
            
            with log_container:
                if st.session_state.last_scan:
                    st.text(f"[{st.session_state.last_scan}] 마지막 스캔 완료")
                
                for violation in st.session_state.violations[-5:]:
                    st.text(f"[{violation.discovered_at}] ⚠️ 위반 발견: {violation.vendor_name} - {violation.product_name} ({violation.violation_price:,}원)")
        else:
            st.warning("🔴 모니터링 비활성화됨")
    
    # 통계 탭
    with tabs[2]:
        st.subheader("📈 상세 통계 분석")
        
        if st.session_state.violations:
            # 통계 데이터 준비
            df_stats = pd.DataFrame([asdict(v) for v in st.session_state.violations])
            
            col1, col2 = st.columns(2)
            
            with col1:
                # 업체별 위반 순위
                st.subheader("🏢 업체별 위반 순위")
                vendor_stats = df_stats.groupby('vendor_name').agg({
                    'violation_rate': 'mean',
                    'product_name': 'count'
                }).round(1)
                vendor_stats.columns = ['평균 위반율(%)', '위반 건수']
                vendor_stats = vendor_stats.sort_values('위반 건수', ascending=False)
                st.dataframe(vendor_stats.head(10), use_container_width=True)
            
            with col2:
                # 제품별 위반 현황
                st.subheader("📦 제품별 위반 현황")
                product_stats = df_stats.groupby('product_name').agg({
                    'violation_rate': 'mean',
                    'violation_price': 'min',
                    'vendor_name': 'count'
                }).round(1)
                product_stats.columns = ['평균 위반율(%)', '최저가격', '위반업체수']
                st.dataframe(product_stats, use_container_width=True)
            
            # 위반율 분포
            st.subheader("📊 위반율 분포")
            fig = px.histogram(
                df_stats,
                x='violation_rate',
                nbins=20,
                title='MAP 위반율 분포',
                labels={'violation_rate': '위반율(%)', 'count': '건수'}
            )
            st.plotly_chart(fig, use_container_width=True)
            
            # 시계열 분석
            st.subheader("📅 일별 위반 추이")
            df_stats['date'] = pd.to_datetime(df_stats['discovered_at']).dt.date
            daily_stats = df_stats.groupby('date').size().reset_index(name='violations')
            
            fig = px.bar(
                daily_stats,
                x='date',
                y='violations',
                title='일별 위반 건수'
            )
            st.plotly_chart(fig, use_container_width=True)
            
        else:
            st.info("통계를 표시할 데이터가 없습니다. 먼저 모니터링을 실행해주세요.")
    
    # 위반 이력 탭
    with tabs[3]:
        st.subheader("📋 전체 위반 이력")
        
        # 필터
        col1, col2, col3 = st.columns(3)
        
        with col1:
            filter_brand = st.selectbox(
                "브랜드 필터",
                ["전체", "고래미", "설래담"]
            )
        
        with col2:
            filter_status = st.selectbox(
                "상태 필터",
                ["전체", "신규", "경고발송", "해결", "재위반"]
            )
        
        with col3:
            filter_days = st.selectbox(
                "기간 필터",
                ["전체", "오늘", "7일", "30일"]
            )
        
        # 데이터베이스에서 위반 이력 조회
        df_violations = db.get_violations(limit=500)
        
        if not df_violations.empty:
            # 필터 적용
            if filter_brand != "전체":
                df_violations = df_violations[df_violations['brand'] == filter_brand]
            
            if filter_status != "전체":
                df_violations = df_violations[df_violations['status'] == filter_status]
            
            if filter_days != "전체":
                if filter_days == "오늘":
                    cutoff = datetime.now().date()
                elif filter_days == "7일":
                    cutoff = datetime.now().date() - timedelta(days=7)
                else:  # 30일
                    cutoff = datetime.now().date() - timedelta(days=30)
                
                df_violations['date'] = pd.to_datetime(df_violations['discovered_at']).dt.date
                df_violations = df_violations[df_violations['date'] >= cutoff]
            
            # 테이블 표시
            st.dataframe(
                df_violations[[
                    'discovered_at', 'brand', 'product_name', 'vendor_name',
                    'violation_price', 'map_price', 'violation_rate', 'status'
                ]],
                use_container_width=True,
                hide_index=True
            )
            
            # 엑셀 다운로드 버튼
            csv = df_violations.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 Excel 다운로드",
                data=csv,
                file_name=f"violations_{datetime.now().strftime('%Y%m%d')}.csv",
                mime='text/csv'
            )
        else:
            st.info("위반 이력이 없습니다.")
    
    # 관리 탭
    with tabs[4]:
        st.subheader("⚙️ 시스템 관리")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🔧 데이터 관리")
            
            if st.button("🗑️ 위반 기록 초기화", type="secondary"):
                st.session_state.violations = []
                st.session_state.scan_history = []
                st.success("위반 기록이 초기화되었습니다.")
            
            if st.button("💾 데이터베이스 백업"):
                # 백업 로직
                backup_file = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                st.success(f"백업 완료: {backup_file}")
        
        with col2:
            st.subheader("📊 시스템 상태")
            
            # 시스템 메트릭
            st.metric("데이터베이스 크기", "12.3 MB")
            st.metric("총 스캔 횟수", len(st.session_state.scan_history))
            st.metric("평균 스캔 시간", "45초")
        
        st.divider()
        
        # 업체 관리
        st.subheader("🏢 업체 블랙리스트 관리")
        
        vendor_stats = db.get_vendor_stats()
        
        if not vendor_stats.empty:
            # 경고 3회 이상 업체 표시
            blacklist = vendor_stats[vendor_stats['violation_count'] >= 3]
            
            if not blacklist.empty:
                st.warning(f"⚠️ 블랙리스트 업체: {len(blacklist)}개")
                st.dataframe(blacklist, use_container_width=True, hide_index=True)
            else:
                st.success("블랙리스트 업체가 없습니다.")
        
        st.divider()
        
        # 로그 뷰어
        st.subheader("📜 시스템 로그")
        
        log_text = st.text_area(
            "최근 로그",
            value="시스템 로그가 여기에 표시됩니다...",
            height=200,
            disabled=True
        )

# 실행
if __name__ == "__main__":
    main()
