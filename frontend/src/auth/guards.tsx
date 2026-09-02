import{Navigate,useLocation}from"react-router-dom";import{useAuth}from"./AuthContext";import{Loading}from"../components/States";
export function CustomerProtectedRoute({children}:{children:React.ReactNode}){const{user,loading}=useAuth();const location=useLocation();if(loading)return <Loading/>;if(!user)return <Navigate to={"/login?next="+encodeURIComponent(location.pathname)} replace/>;if(user.is_staff)return <Navigate to="/forbidden" replace/>;return children}
export function StaffProtectedRoute({children}:{children:React.ReactNode}){const{user,loading}=useAuth();if(loading)return <Loading/>;if(!user)return <Navigate to="/staff/login" replace/>;if(!user.is_staff)return <Navigate to="/forbidden" replace/>;return children}
export function PermissionProtectedRoute({permission,children}:{permission:string;children:React.ReactNode}){const{user}=useAuth();return user?.is_superuser||user?.permissions.includes(permission)?children:<Navigate to="/forbidden" replace/>}

