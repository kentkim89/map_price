#!/usr/bin/env python3
"""
MAP 가격 모니터링 시스템 - Streamlit Cloud 버전
고래미 & 설래담 브랜드 MAP 정책 관리
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import time
import random
from typing import List, Dict, Optional
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import re

# 페이지 설정
st.set_page_config(
    page_title="MAP 가격 모니터링",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 세션 상태 초기화
if 'violations' not in st.session_state:
    st.session_state.violations = []
if 'scan_history' not in st.session_state:
    st.session_state.scan_history = []
if 'last_scan' not in st.session_state:
    st.session_state.last_scan = None

# CSS 스타일
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
        padding: 1rem;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .violation-alert {
        background-color: #ffebee;
        border-left: 4px solid #f44336;
        padding: 1rem;
        margin: 1rem 0;
        border-radius: 4px;
    }
    .success-alert {
        background-color: #e8f5e9;
        border-left: 4px solid #4caf50;
        padding: 1rem;
        margin: 1rem 0;
        border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)

# 크롤링 함수 (Streamlit Cloud용 수정)
def setup_chrome_options():
    """Chrome 옵션 설정 - Streamlit Cloud 환경"""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-features=VizDisplayCompositor')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    return options

def extract_price(price_text: str) -> Optional[int]:
    """가격 추출"""
    try:
        price = re.sub(r'[^\d]', '', price_text)
        return int(price) if price else None
    except:
        return None

def crawl_product(product: dict, progress_bar=None, status_text=None) -> List[dict]:
    """제품 크롤링 (간소화 버전)"""
    violations = []
    
    try:
        if status_text:
            status_text.text(f"🔍 검색 중: {product['name']}")
        
        # Selenium 대신 더미 데이터 생성 (Streamlit Cloud에서는 Selenium 제한적)
        # 실제 배포시에는 API나 다른 방법 사용 권장
        
        # 시뮬레이션 데이터
        sample_vendors = ["A마켓", "B쇼핑", "C몰", "D스토어", "E마트"]
        
        for vendor in random.sample(sample_vendors, random.randint(0, 3)):
            # 랜덤하게 위반 생성
            if random.random() > 0.5:  # 50% 확률로 위반
                violation_price = int(product['map_price'] * random.uniform(0.85, 0.95))
                
                violations.append({
                    'brand': product['brand'],
                    'product_name': product['name'],
                    'map_price': product['map_price'],
                    'vendor_name': vendor,
                    'violation_price': violation_price,
                    'violation_rate': round((product['map_price'] - violation_price) / product['map_price'] * 100, 1),
                    'discovered_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'status': '신규'
                })
        
        # 진행 상황 업데이트
        if progress_bar:
            progress_bar.progress(1.0)
            
    except Exception as e:
        if status_text:
            status_text.text(f"❌ 오류: {str(e)}")
    
    return violations

# 메인 헤더
st.markdown('<h1 class="main-header">🔍 MAP 가격 모니터링 시스템</h1>', unsafe_allow_html=True)
st.markdown("### 고래미 & 설래담 브랜드 가격 정책 관리 대시보드")

# 사이드바 설정
with st.sidebar:
    st.header("⚙️ 설정")
    
    # 제품 관리
    st.subheader("📦 제품 관리")
    
    products = []
    
    # 고래미 제품
    with st.expander("🐋 고래미 브랜드", expanded=True):
        tako_price = st.number_input(
            "타코와사비 MAP (원)",
            value=18000,
            min_value=1000,
            step=1000,
            key="tako"
        )
        products.append({
            'brand': '고래미',
            'name': '고래미 타코와사비',
            'map_price': tako_price
        })
        
        gani_price = st.number_input(
            "가니미소 MAP (원)",
            value=25000,
            min_value=1000,
            step=1000,
            key="gani"
        )
        products.append({
            'brand': '고래미',
            'name': '고래미 가니미소',
            'map_price': gani_price
        })
    
    # 설래담 제품
    with st.expander("🍲 설래담 브랜드", expanded=True):
        yeonpo_price = st.number_input(
            "연포탕 MAP (원)",
            value=32000,
            min_value=1000,
            step=1000,
            key="yeonpo"
        )
        products.append({
            'brand': '설래담',
            'name': '설래담 연포탕',
            'map_price': yeonpo_price
        })
    
    st.divider()
    
    # 알림 설정
    st.subheader("🔔 알림 설정")
    
    slack_webhook = st.text_input(
        "Slack Webhook URL",
        type="password",
        placeholder="https://hooks.slack.com/..."
    )
    
    email_notification = st.text_input(
        "알림 이메일",
        placeholder="admin@company.com"
    )

# 메인 컨텐츠 - 탭
tab1, tab2, tab3, tab4 = st.tabs(["📊 대시보드", "🔍 실시간 모니터링", "📈 통계", "📋 위반 이력"])

# 대시보드 탭
with tab1:
    # 메트릭 표시
    col1, col2, col3, col4 = st.columns(4)
    
    today_violations = [v for v in st.session_state.violations 
                       if v.get('discovered_at', '').startswith(datetime.now().strftime("%Y-%m-%d"))]
    
    with col1:
        st.metric(
            "오늘 위반 건수",
            f"{len(today_violations)}건",
            delta=f"+{len(today_violations)}" if today_violations else "0"
        )
    
    with col2:
        st.metric(
            "총 위반 건수",
            f"{len(st.session_state.violations)}건"
        )
    
    with col3:
        if st.session_state.violations:
            avg_rate = sum(v['violation_rate'] for v in st.session_state.violations) / len(st.session_state.violations)
            st.metric(
                "평균 위반율",
                f"{avg_rate:.1f}%",
                delta="MAP 위반"
            )
        else:
            st.metric("평균 위반율", "0%")
    
    with col4:
        if st.session_state.last_scan:
            st.metric(
                "마지막 스캔",
                st.session_state.last_scan
            )
        else:
            st.metric("마지막 스캔", "대기 중")
    
    st.divider()
    
    # 최근 위반 내역
    st.subheader("🚨 최근 위반 내역")
    
    if st.session_state.violations:
        df_violations = pd.DataFrame(st.session_state.violations[-10:])
        
        # 컬럼 순서 조정
        columns = ['discovered_at', 'brand', 'product_name', 'vendor_name', 
                  'violation_price', 'map_price', 'violation_rate', 'status']
        df_violations = df_violations[columns]
        
        # 컬럼명 한글화
        df_violations.columns = ['발견시간', '브랜드', '제품명', '업체명', 
                                '위반가격', 'MAP', '위반율(%)', '상태']
        
        st.dataframe(
            df_violations,
            use_container_width=True,
            hide_index=True
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
                brand = v['brand']
                brand_counts[brand] = brand_counts.get(brand, 0) + 1
            
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
with tab2:
    st.subheader("🔍 실시간 가격 모니터링")
    
    col1, col2, col3 = st.columns(3)
    
    with col2:
        if st.button("🚀 즉시 스캔 시작", type="primary", use_container_width=True):
            with st.spinner("스캔 중..."):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                all_violations = []
                
                for i, product in enumerate(products):
                    progress = (i + 1) / len(products)
                    progress_bar.progress(progress)
                    
                    # 크롤링 실행
                    violations = crawl_product(product, progress_bar, status_text)
                    all_violations.extend(violations)
                    
                    time.sleep(1)  # 시뮬레이션 딜레이
                
                # 결과 저장
                st.session_state.violations.extend(all_violations)
                st.session_state.last_scan = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.session_state.scan_history.append({
                    'time': st.session_state.last_scan,
                    'violations': len(all_violations)
                })
                
                progress_bar.empty()
                status_text.empty()
                
                if all_violations:
                    st.success(f"✅ 스캔 완료! {len(all_violations)}건의 위반을 발견했습니다.")
                    st.balloons()
                    
                    # 위반 상세 표시
                    for v in all_violations:
                        st.markdown(f"""
                        <div class="violation-alert">
                        <strong>⚠️ 위반 발견</strong><br>
                        제품: {v['product_name']}<br>
                        업체: {v['vendor_name']}<br>
                        위반가격: {v['violation_price']:,}원 (MAP: {v['map_price']:,}원)<br>
                        위반율: {v['violation_rate']}%
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    st.info("스캔 완료! 위반 사항이 없습니다.")
    
    st.divider()
    
    # 실시간 로그
    st.subheader("📝 실시간 활동 로그")
    
    log_container = st.container()
    with log_container:
        if st.session_state.last_scan:
            st.text(f"[{st.session_state.last_scan}] 마지막 스캔 완료")
        
        for violation in st.session_state.violations[-5:]:
            st.text(f"[{violation['discovered_at']}] ⚠️ {violation['vendor_name']} - {violation['product_name']} ({violation['violation_price']:,}원)")

# 통계 탭
with tab3:
    st.subheader("📈 상세 통계 분석")
    
    if st.session_state.violations:
        df_stats = pd.DataFrame(st.session_state.violations)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🏢 업체별 위반 순위")
            vendor_stats = df_stats.groupby('vendor_name').agg({
                'violation_rate': 'mean',
                'product_name': 'count'
            }).round(1)
            vendor_stats.columns = ['평균 위반율(%)', '위반 건수']
            vendor_stats = vendor_stats.sort_values('위반 건수', ascending=False)
            st.dataframe(vendor_stats, use_container_width=True)
        
        with col2:
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
    else:
        st.info("통계를 표시할 데이터가 없습니다. 먼저 모니터링을 실행해주세요.")

# 위반 이력 탭
with tab4:
    st.subheader("📋 전체 위반 이력")
    
    if st.session_state.violations:
        # 필터
        col1, col2, col3 = st.columns(3)
        
        with col1:
            filter_brand = st.selectbox("브랜드", ["전체", "고래미", "설래담"])
        
        with col2:
            filter_status = st.selectbox("상태", ["전체", "신규", "처리중", "완료"])
        
        with col3:
            if st.button("🗑️ 데이터 초기화"):
                st.session_state.violations = []
                st.session_state.scan_history = []
                st.rerun()
        
        # 데이터 필터링
        df_all = pd.DataFrame(st.session_state.violations)
        
        if filter_brand != "전체":
            df_all = df_all[df_all['brand'] == filter_brand]
        
        if filter_status != "전체":
            df_all = df_all[df_all['status'] == filter_status]
        
        # 테이블 표시
        st.dataframe(df_all, use_container_width=True, hide_index=True)
        
        # CSV 다운로드
        csv = df_all.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="📥 CSV 다운로드",
            data=csv,
            file_name=f"violations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime='text/csv'
        )
    else:
        st.info("위반 이력이 없습니다.")

# 푸터
st.divider()
st.markdown("""
<div style='text-align: center; color: #888; padding: 1rem;'>
    MAP 가격 모니터링 시스템 v1.0 | 고래미 & 설래담
</div>
""", unsafe_allow_html=True)
