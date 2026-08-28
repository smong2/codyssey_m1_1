// src/gnb.js
window.GNB = function GNB() {
	const currentPath = window.location.pathname;

	const navLinks = [
		{ path: "/", label: "홈 (대시보드)" },
		{ path: "/data.html", label: "1. 데이터 수집" },
		{ path: "/eda.html", label: "2. 탐색적 분석(EDA)" },
		{ path: "/predict.html", label: "3. 시계열 예측" },
		{ path: "/report.html", label: "4. 종합 리포트" },
	];

	return (
		<nav className="bg-white border-b border-slate-200 sticky top-0 z-50 shadow-sm no-print">
			<div className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8">
				<div className="flex justify-between items-center h-14">
					<div className="flex items-center gap-8">
						<span className="text-lg font-black text-brand-600 tracking-tight">WeatherLoad</span>
						<div className="hidden sm:flex space-x-6 overflow-x-auto">
							{navLinks.map((link) => {
								// 루트('/') 경로와 '/index.html'을 동일하게 취급
								const isActive = currentPath === link.path || (currentPath === "/index.html" && link.path === "/");
								return (
									<a key={link.path} href={link.path} className={`px-1 py-4 border-b-2 text-sm font-bold transition whitespace-nowrap ${isActive ? "text-brand-600 border-brand-600" : "text-slate-500 hover:text-slate-900 border-transparent hover:border-slate-300"}`}>
										{link.label}
									</a>
								);
							})}
						</div>
					</div>
				</div>
			</div>
		</nav>
	);
};
